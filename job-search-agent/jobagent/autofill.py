"""Autofill: screening question text -> candidate_facts value, then fill the form.

Absolute rule: if a required value is blank in facts, DO NOT guess. Return the
missing field so the caller fails that application and emails it.
Never type PAN/Aadhaar/passwords anywhere.
"""

from __future__ import annotations

import re
import time

from .facts import Facts
from .logging_setup import get_logger
from .textutil import normalize_ws

log = get_logger("jobagent.autofill")


class Autofill:
    def __init__(self, facts: Facts, llm=None):
        self.facts = facts
        self.llm = llm

    def resolve(self, question: str) -> tuple[str | None, str | None]:
        """Deterministic first. Returns (value, fact_key). (None, key) = known-but-blank."""
        value, key = self.facts.answer_for_question(question)
        if value is not None:
            return value, key
        if key is not None:
            return None, key
        # optional LLM mapping ONLY for a known list of stored facts (no invention)
        if self.llm is not None:
            pass  # intentionally not used for values; keep deterministic and safe
        return None, None

    # ---- LinkedIn dialog (current UI: native <dialog>, hashed classes) ----
    def fill_dialog(self, page, facts: Facts,
                    resume_path: str | None = None) -> tuple[list[str], list[str]]:
        """Fill every answerable control in the open Easy Apply dialog step.

        Returns (missing, notes). missing holds facts keys (or "question: ..."
        for required questions with no stored answer); notes holds benign
        observations (e.g. kept the account-default email).
        """
        from .browser import linkedin as _li
        missing: list[str] = []
        notes: list[str] = []
        dialog = _li.find_easy_apply_dialog(page)
        scope = dialog or page
        if dialog is None:
            return missing, notes

        for finput in self._visible(scope, "input[type='file']"):
            miss, note = self._fill_file(finput, facts, resume_path)
            missing += miss
            notes += note

        for name, radios in self._radio_groups(scope).items():
            miss = self._fill_radio_group(page, radios)
            missing += miss

        for sel in self._visible(scope, "select"):
            miss, note = self._fill_select(page, sel, facts)
            missing += miss
            notes += note

        for inp in self._visible(scope,
                                 "input[type='text'], input[type='tel'], "
                                 "input[type='email'], input[type='number'], "
                                 "input[type='url'], input:not([type]), textarea"):
            if self._is_hidden_type(inp):
                continue
            label = self._field_label(page, inp)
            value, key = self.resolve(label)
            if value is None:
                if self._required(inp, label, self._block_text(inp)) and key:
                    missing.append(key)
                elif self._required(inp, label, self._block_text(inp)):
                    missing.append(f"question: {normalize_question(label)[:80]}")
                continue
            self._set_input(inp, value)
            time.sleep(0.2)
        return self._dedupe(missing), notes

    @staticmethod
    def _block_text(element) -> str:
        """Surrounding block text, for catching '*' required markers that live
        outside the label itself."""
        try:
            return normalize_ws(element.evaluate(
                "e => { const b = e.closest('fieldset') || e.parentElement; "
                "return b ? b.innerText : ''; }") or "")
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _visible(scope, selector: str) -> list:
        try:
            return [e for e in scope.query_selector_all(selector)
                    if e.is_visible()]
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _is_hidden_type(element) -> bool:
        try:
            return (element.evaluate("e => e.tagName.toLowerCase()") == "input"
                    and (element.get_attribute("type") or "").lower()
                    in {"hidden", "submit", "button", "radio", "checkbox", "file"})
        except Exception:  # noqa: BLE001
            return True

    def _field_label(self, page, element) -> str:
        """Best-effort label: aria-label, <label for=id>, wrapping label, nearby text."""
        try:
            aria = (element.get_attribute("aria-label") or "").strip()
            if aria:
                return aria
            el_id = element.get_attribute("id") or ""
            if el_id:
                lab = page.query_selector(f"label[for='{el_id}']")
                if lab and (lab.inner_text() or "").strip():
                    return lab.inner_text().strip()
            wrap = element.evaluate(
                "e => { const l = e.closest('label'); "
                "return l ? l.innerText : ''; }")
            if (wrap or "").strip():
                return normalize_ws(wrap)
            parent = element.evaluate(
                "e => e.parentElement ? e.parentElement.innerText : ''")
            first = normalize_ws(parent or "").split("\n")[0]
            return first[:120]
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _required(element, label: str, block_text: str = "") -> bool:
        try:
            if element.get_attribute("aria-required") == "true":
                return True
            if element.get_attribute("required") is not None:
                return True
        except Exception:  # noqa: BLE001
            pass
        return "*" in (label or "") or "*" in (block_text or "")

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        return list(dict.fromkeys(items))

    def _fill_file(self, element, facts: Facts,
                   resume_path: str | None) -> tuple[list[str], list[str]]:
        import os
        if not resume_path or not os.path.exists(resume_path):
            return ["application.resume_files"], []
        try:
            if os.path.getsize(resume_path) > 2 * 1024 * 1024:
                return ["application.resume_files"], ["resume over 2MB; skipped"]
            element.set_input_files(resume_path)
            return [], ["resume attached"]
        except Exception as e:  # noqa: BLE001
            log.debug("resume upload failed: %s", e)
            return ["application.resume_files"], []

    def _radio_groups(self, scope) -> dict:
        groups: dict = {}
        # NOTE: no visibility filter here. Custom-styled radios hide the
        # native input (LinkedIn does this); filtering would drop every real
        # group. _check_radio handles visible vs force clicking instead.
        try:
            radios = scope.query_selector_all("input[type='radio']")
        except Exception:  # noqa: BLE001
            return {}
        for r in radios or []:
            try:
                key = r.get_attribute("name") or f"anon-{id(r)}"
            except Exception:  # noqa: BLE001
                continue
            groups.setdefault(key, []).append(r)
        return groups

    def _option_text(self, radio) -> str:
        """The option's OWN label (Yes/No/2-3 years) — never the shared question.

        Priority: <label for=id>, wrapping <label>, short ancestor text (the
        visible Yes/No span next to custom-styled hidden inputs), meaningful
        value attr. Generic values (on/off/true/false) and long aria questions
        are skipped.
        """
        try:
            el_id = radio.get_attribute("id") or ""
            if el_id:
                lab = radio.evaluate(
                    "e => { const l = document.querySelector("
                    "\"label[for='\" + e.id + \"']\"); "
                    "return l ? l.innerText : ''; }")
                if (lab or "").strip():
                    return normalize_ws(lab)
            wrap = radio.evaluate(
                "e => { const p = e.closest('label'); "
                "return p ? p.innerText : ''; }")
            if (wrap or "").strip():
                return normalize_ws(wrap)
            sib = radio.evaluate(
                "e => { let p = e.parentElement; "
                "for (let i = 0; i < 4 && p; i++, p = p.parentElement) { "
                "const t = (p.innerText || '').trim(); "
                "if (t && t.length <= 40) return t; } return ''; }")
            if (sib or "").strip():
                return normalize_ws(sib)
            val = (radio.get_attribute("value") or "").strip()
            if val and val.lower() not in {"on", "off", "true", "false"}:
                return val
            aria = (radio.get_attribute("aria-label") or "").strip()
            if aria and len(aria) <= 40:
                return aria
            return ""
        except Exception:  # noqa: BLE001
            return ""

    def _radio_text(self, radio) -> str:
        # Kept for compatibility; prefers the shared question text.
        try:
            for attr in ("aria-label", "value"):
                val = (radio.get_attribute(attr) or "").strip()
                if val:
                    return val
            return self._option_text(radio)
        except Exception:  # noqa: BLE001
            return ""

    def _group_question(self, radios: list) -> str:
        """The question a radio group answers. Option labels ("Yes"/"No") are
        NOT the question — it lives in the surrounding container (fieldset
        legend or section text above the options)."""
        try:
            container = radios[0].evaluate(
                "e => { const f = e.closest('fieldset') || "
                "(e.parentElement ? e.parentElement.parentElement : null); "
                "return f ? f.innerText : ''; }")
        except Exception:  # noqa: BLE001
            container = ""
        question = normalize_ws(container or "")
        for _, text in [(r, self._option_text(r)) for r in radios]:
            if text:
                question = question.replace(text, " ")
        return normalize_ws(question)[:200]

    def _fill_radio_group(self, page, radios: list) -> list[str]:
        """Answer only with a stored fact. Yes/No matched exactly; numbers must
        fall inside exactly one labeled range; anything else is left blank."""
        texts = [(r, self._option_text(r)) for r in radios]
        # The shared aria-label often IS the full question (same on every
        # option); prefer it over container scraping when present.
        shared = set()
        for r in radios:
            try:
                aria = (r.get_attribute("aria-label") or "").strip()
            except Exception:  # noqa: BLE001
                aria = ""
            if len(aria) > 30:
                shared.add(aria)
        if len(shared) == 1:
            question = next(iter(shared))[:200]
        else:
            question = self._group_question(radios)
        if not question:
            question = " / ".join(t for _, t in texts if t)[:160]
        value, key = self.resolve(question)
        if value is None:
            # LinkedIn marks required questions with "*" in the text; treat
            # those (plus aria-required, plus block-level asterisks) as
            # blocking — never skip a required question silently.
            block_star = "*" in self._block_text(radios[0])
            if "*" in question or block_star or any(
                    self._is_required_radio(r) for r in radios):
                return [key or f"question: {normalize_question(question)[:80]}"]
            return []
        want = value.strip().lower()
        # Exact matches first (a "Yes No" blob must not beat a real "Yes").
        for radio, text in texts:
            if text.strip().lower() and text.strip().lower() == want:
                self._check_radio(radio, text)
                return []
        for radio, text in texts:
            low = text.strip().lower()
            if low and want in ("yes", "no") and low.startswith(want):
                self._check_radio(radio, text)
                return []
        if want.replace(".", "", 1).isdigit():
            num = float(want)
            for radio, text in texts:
                bounds = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)[:2]]
                if len(bounds) == 2 and bounds[0] <= num <= bounds[1]:
                    self._check_radio(radio, text)
                    return []
                if len(bounds) == 1 and ("+" in text or "more" in text.lower()) \
                        and num >= bounds[0]:
                    self._check_radio(radio, text)
                    return []
        return [key or f"question: {normalize_question(question)[:80]}"]

    @staticmethod
    def _check_radio(radio, option_text: str = "") -> bool:
        """Select a radio option; True if it reads back checked.

        Custom-styled radios hide the native input, so a direct check can land
        on empty coordinates. Prefer clicking the visible widget carrying the
        option text (the same control a human clicks); fall back to a forced
        check of the input itself.
        """
        if option_text and Autofill._click_widget(radio, option_text):
            if Autofill._is_checked(radio):
                time.sleep(0.2)
                return True
        try:
            visible = radio.is_visible()
        except Exception:  # noqa: BLE001
            visible = False
        try:
            if visible:
                radio.check(timeout=8000)
            else:
                radio.check(force=True, timeout=8000)
            time.sleep(0.2)
        except Exception as e:  # noqa: BLE001
            log.debug("radio check failed: %s", e)
        return Autofill._is_checked(radio)

    @staticmethod
    def _click_widget(radio, option_text: str) -> bool:
        """Click the visible element showing exactly option_text near the radio."""
        try:
            return bool(radio.evaluate(
                """(e, want) => {
                  const doc = e.ownerDocument;
                  let scope = e.parentElement;
                  for (let i = 0; i < 6 && scope; i++, scope = scope.parentElement) {
                    const t = (scope.innerText || '');
                    if (t.toLowerCase().includes(want.toLowerCase())) break;
                  }
                  if (!scope) return false;
                  const walker = doc.createTreeWalker(scope, NodeFilter.SHOW_ELEMENT);
                  let node;
                  while (node = walker.nextNode()) {
                    const tag = node.tagName.toLowerCase();
                    if (['input','select','textarea','button','a'].includes(tag)) continue;
                    const own = Array.from(node.childNodes)
                      .filter(n => n.nodeType === 3)
                      .map(n => n.textContent.trim()).join(' ');
                    if (own && own.toLowerCase() === want.toLowerCase()) {
                      node.click(); return true;
                    }
                  }
                  return false;
                }""", option_text))
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _is_checked(radio) -> bool:
        try:
            return bool(radio.is_checked())
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _is_required_radio(radio) -> bool:
        try:
            return radio.get_attribute("aria-required") == "true"
        except Exception:  # noqa: BLE001
            return False

    def _fill_select(self, page, element, facts: Facts) -> tuple[list[str], list[str]]:
        try:
            options = element.evaluate(
                "e => Array.from(e.options).map(o => (o.text + '|||' + o.value))")
        except Exception:  # noqa: BLE001
            return [], []
        try:
            label = self._field_label(page, element)
        except Exception:  # noqa: BLE001
            label = ""
        low = label.lower()
        # Phone country code: match the parenthesized dial code EXACTLY.
        # Substring matching is wrong here ("91" is inside Bolivia's "+591").
        if "countr" in low or any(re.search(r"\+\d{1,4}", (o.split("|||")[0] + o.split("|||")[-1])) for o in options):
            want_digits = re.sub(r"\D", "", str(facts.get("identity.phone_country_code") or ""))
            for opt in options:
                text, _, val = opt.partition("|||")
                m = re.search(r"\(\s*\+?(\d{1,4})\s*\)", text)
                code = m.group(1) if m else re.sub(r"\D", "", val)
                if want_digits and code == want_digits:
                    self._select_option(element, text.strip(), val)
                    return [], []
            return ["identity.phone_country_code"], []
        # Account email list: prefer the facts address only if offered.
        if "email" in low:
            want = str(facts.get("identity.email") or "").strip().lower()
            for opt in options:
                text, _, val = opt.partition("|||")
                if want and (want == text.strip().lower() or want == val.strip().lower()):
                    self._select_option(element, text.strip(), val)
                    return [], [f"email set to {want}"]
            return [], ["kept account-default email (facts email not offered)"]
        value, key = self.resolve(label)
        if value is None:
            if self._required(element, label):
                return [key or f"question: {normalize_question(label)[:80]}"], []
            return [], []
        for opt in options:
            text, _, val = opt.partition("|||")
            if text.strip().lower() == value.strip().lower():
                self._select_option(element, text.strip(), val)
                return [], []
        return [key or f"question: {normalize_question(label)[:80]}"], []

    def _select_option(self, element, label: str, value: str) -> None:
        try:
            element.select_option(label=label)
        except Exception:  # noqa: BLE001
            try:
                element.select_option(value=value)
            except Exception as e:  # noqa: BLE001
                log.debug("select failed: %s", e)

    def _set_input(self, element, value: str) -> None:
        try:
            tag = element.evaluate("e => e.tagName.toLowerCase()")
            if tag == "select":
                try:
                    element.select_option(label=str(value))
                    return
                except Exception:  # noqa: BLE001
                    element.select_option(value=str(value))
                    return
            element.fill(str(value))
        except Exception as e:  # noqa: BLE001
            log.debug("set_input failed: %s", e)

    # ---- Naukri questions -------------------------------------------------
    def fill_naukri_questions(self, page, facts: Facts) -> list[str]:
        """Answer Naukri recruiter questions. Handles two surfaces:

        1. Chatbot modal (.chatbot_MessageContainer): bot messages in
           li.botItem .botMsg, answer box is a contenteditable div
           (NOT input/textarea/select). Loop: read last question, resolve,
           type + Enter, wait for the next question, up to 10 turns.
        2. Legacy inline blocks (.qa-question/.form-group/.question) with
           real inputs — previous behavior, kept as fallback.
        """
        missing: list[str] = []
        chats = []
        try:
            chats = page.query_selector_all(".chatbot_MessageContainer")
        except Exception:  # noqa: BLE001
            chats = []
        if chats:
            for chat in chats:
                miss = self._fill_naukri_chat(page, chat, facts)
                missing += miss
            return self._dedupe(missing)
        for block in page.query_selector_all(".qa-question, .form-group, .question"):
            try:
                label = (block.inner_text() or "")
                inp = block.query_selector("input, textarea, select")
                if not inp:
                    continue
                value, key = self.resolve(label)
                if value is None:
                    if key:
                        missing.append(key)
                    continue
                self._set_input(inp, value)
                time.sleep(0.2)
            except Exception:  # noqa: BLE001
                continue
        return missing

    def _naukri_bot_texts(self, chat) -> list[str]:
        try:
            nodes = chat.query_selector_all("li.botItem .botMsg, .botMsg span")
        except Exception:  # noqa: BLE001
            return []
        texts: list[str] = []
        for n in nodes or []:
            try:
                t = normalize_ws(n.inner_text() or "")
            except Exception:  # noqa: BLE001
                continue
            if t and t not in texts:
                texts.append(t)
        return texts

    def _naukri_chat_box(self, page, chat):
        """The answer widget: contenteditable div first, then classic inputs."""
        for sel in ("[contenteditable='true']", "[contenteditable=true]",
                    "div.textArea", "textarea", "input[type='text'], input:not([type])"):
            try:
                box = chat.query_selector(sel)
                if box:
                    return box
            except Exception:  # noqa: BLE001
                continue
        try:
            return page.query_selector("[contenteditable='true']")
        except Exception:  # noqa: BLE001
            return None

    def _fill_naukri_chat(self, page, chat, facts: Facts) -> list[str]:
        missing: list[str] = []
        seen_count = 0
        for _ in range(10):
            texts = self._naukri_bot_texts(chat)
            if len(texts) < seen_count:
                seen_count = len(texts)
            new_texts = texts[seen_count:] or texts[-1:]
            question = ""
            for t in reversed(new_texts):
                value, key = self.resolve(t)
                if value is not None or key is not None:
                    question = t
                    break
            if not question:
                # Nothing answerable among new messages. If the latest message
                # is a question we cannot map, fail loudly; greetings (no "?")
                # mean the turn is over.
                latest = texts[-1] if texts else ""
                if "?" in latest:
                    missing.append(f"question: {normalize_question(latest)[:80]}")
                    return self._dedupe(missing)
                return self._dedupe(missing)
            value, key = self.resolve(question)
            if value is None:
                missing.append(key or f"question: {normalize_question(question)[:80]}")
                return self._dedupe(missing)
            box = self._naukri_chat_box(page, chat)
            if box is None:
                missing.append(key or f"question: {normalize_question(question)[:80]}")
                return self._dedupe(missing)
            self._send_chat(box, value)
            time.sleep(2.5)
            updated = self._naukri_bot_texts(chat)
            if len(updated) <= len(texts):
                # No follow-up question (yet) — re-read once after a longer wait
                # in case the bot is slow, then stop; Save handles the rest.
                time.sleep(2.5)
                updated = self._naukri_bot_texts(chat)
                if len(updated) <= len(texts):
                    seen_count = len(updated)
                    break
            seen_count = len(texts)
        return self._dedupe(missing)

    @staticmethod
    def _send_chat(box, value: str) -> None:
        """Type into a contenteditable chat box and send with Enter."""
        text = str(value)
        try:
            box.click()
        except Exception:  # noqa: BLE001
            pass
        try:
            box.fill(text)
        except Exception:  # noqa: BLE001
            try:
                box.evaluate(
                    "(e, v) => { e.focus(); document.execCommand"
                    "('insertText', false, v); e.dispatchEvent("
                    "new InputEvent('input', {bubbles: true})); }", text)
            except Exception:  # noqa: BLE001
                log.debug("chat fill failed")
                return
        try:
            box.press("Enter")
        except Exception:  # noqa: BLE001
            try:
                box.evaluate(
                    "e => e.dispatchEvent(new KeyboardEvent('keydown', "
                    "{key: 'Enter', bubbles: true}))")
            except Exception:  # noqa: BLE001
                log.debug("chat send failed")


def normalize_question(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()
"""Selector candidates. LinkedIn is mid-migration to "AI job search", so every
selector has fallbacks and the collector must fail soft (log + skip) rather than
crash. Verify these against the user's real session in Phase 4 (RUNBOOK.md).
"""

LINKEDIN = {
    # Ground truth 2026-09-28 (user's live feed HTML): LinkedIn now ships hashed
    # CSS-module classes and NO profile-photo classes or aria-labels. The global
    # nav renders <a><span>Jobs</span></a> / <a><span>Me</span></a> inside <nav>.
    # Text-based selectors are the only stable markers; classes are useless.
    "logged_in": "nav:has-text(\"Jobs\")",
    "logged_in_fallbacks": [
        "nav a:text(\"Me\")",
        "a[href*='linkedin.com/jobs']",
    ],
    "job_card": "li.scaffold-layout__list-item, div.job-card-container, li[data-occludable-job-id]",
    "card_title": "a.job-card-container__link, a.job-card-list__title, strong.job-card-container__title",
    "card_company": ".job-card-container__primary-description, .artdeco-entity-lockup__subtitle",
    "card_location": ".job-card-container__metadata-item, .artdeco-entity-lockup__caption",
    "card_posted": "time, .job-card-container__footer-item time",
    "detail_title": ".job-details-jobs-unified-top-card__job-title, h1.t-24",
    "detail_company": ".job-details-jobs-unified-top-card__company-name, a.topcard__org-name-link",
    "detail_location": ".job-details-jobs-unified-top-card__bullet, .topcard__flavor--bullet",
    "detail_posted": ".job-details-jobs-unified-top-card__posted-date, span.tvm__text--low-emphasis",
    "detail_salary": ".job-details-jobs-unified-top-card__job-insight, .compensation__salary",
    # Ground truth 2026-09-28 (live view page): the description is a
    # <span data-testid="expandable-text-box"> after the "About the job" h2.
    # data-testid beats hashed classes for stability.
    "detail_description": "[data-testid='expandable-text-box'], #job-details, .jobs-description__content, .jobs-box__html-content",
    "applicant_count": ".job-details-jobs-unified-top-card__applicant-count, span.tvm__text",
    # Hydration markers: the new search UI streams results client-side, so the
    # collector waits for one of these before reading cards.
    "hydration_markers": [
        "a[href*='currentJobId']",
        "li.scaffold-layout__list-item",
        "div.job-card-container",
    ],
    # Any anchor carrying a currentJobId identifies one posted job.
    "card_link": "a[href*='currentJobId']",
    # The live Easy Apply surface (verified 2026-10-08): a native <dialog>,
    # no role attribute. find_easy_apply_dialog() tries these in order.
    "modal": "dialog.open[data-testid='dialog'], dialog[open][data-testid='dialog'], dialog[open]",
    "easy_apply_button": "button.jobs-apply-button, button[aria-label*='Easy Apply' i]",
    "external_apply_link": "a.jobs-apply-button, a[data-tracking-control-name*='external']",
    "next_page": "button[aria-label='Next'], button.artdeco-pagination__button--next",
}

NAUKRI = {
    "logged_in": "a[href*='/mnjuser/profile'], .nI-gNb-drawer__icon, div.sticky-header",
    "job_card": "div.cust-job-tuple, article.jobTuple, div.srp-jobtuple-wrapper, .jobTuple",
    "card_title": "a.title, a.jobTitle, a[href*='job-listings']",
    "card_company": "a.subTitle, .companyInfo a, .comp-name",
    "card_location": ".location, .locWdth, span.loc",
    "card_posted": "span.job-post-day, .type, .postedDate, span.freshness",
    "card_salary": ".salary, .sal, span.sal",
    "card_experience": ".experience, .expwdth, span.exp",
    # Ground truth 2026-09-28 (live view page): the description div carries a
    # CSS-module class CONTAINING dang-inner-html
    # (<div class="styles_JDC__dang-inner-html__h0K4t">), and the apply control
    # is <button id="company-site-button"> — tag-agnostic #id selectors only.
    "detail_description": ".job-desc, section.job-desc, .dang-inner-html, [class*='dang-inner-html']",
    "apply_button": "#apply-button, .apply-button, #company-site-button",
    "in_platform_apply": "#apply-button",
    "company_site_apply": "#company-site-button",
    # Observed live 2026-10-08: Naukri replaces the apply button with
    # <span id="already-applied" class="... already-applied">Applied</span>
    # once the account has applied (manually or otherwise). Not a failure —
    # it means there is nothing left to do for this job.
    "already_applied": "#already-applied, .already-applied",
    "next_page": "a.paginationNext, a[title='Next']",
}
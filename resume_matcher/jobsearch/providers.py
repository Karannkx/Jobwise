"""Job-board providers.

Every provider exposes ``fetch(http, query, creds) -> list[Posting]`` and a pure ``parse(payload)``
so parsing can be tested without a network. Errors are raised as ``ProviderError`` with a message
that is safe to show (no URLs, no keys).

Attribution: each posting keeps its ``source`` and canonical ``url``; the UI always shows the source
and links to the original listing, as the providers' terms ask.

Notes on individual terms of use (see README): Remotive asks for at most a few requests per day
(responses are cached for hours), Jobicy for no more than hourly polling, Himalayas requires
applying through its ``applicationLink``, and RemoteOK requires a visible link back. Postings are
never forwarded to third parties by this application.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

from .http import HttpClient
from .models import CredField, Posting, ProviderError, SearchQuery
from .util import as_list, clean_text, first, money, parse_dt, strip_html

log = logging.getLogger(__name__)

COUNTRY_NAMES = {
    "in": "India", "gb": "United Kingdom", "us": "United States", "au": "Australia", "at": "Austria",
    "be": "Belgium", "br": "Brazil", "ca": "Canada", "ch": "Switzerland", "de": "Germany", "es": "Spain",
    "fr": "France", "it": "Italy", "mx": "Mexico", "nl": "Netherlands", "nz": "New Zealand", "pl": "Poland",
    "sg": "Singapore", "za": "South Africa", "ae": "United Arab Emirates", "ie": "Ireland",
}
ADZUNA_COUNTRIES = ["in", "gb", "us", "au", "at", "be", "br", "ca", "ch", "de", "es", "fr", "it", "mx", "nl", "nz", "pl", "sg", "za"]
_REMOTE_RE = re.compile(r"\b(remote|work from home|wfh|anywhere)\b", re.I)


def _is_remote_text(*parts: Optional[str]) -> Optional[bool]:
    return True if any(p and _REMOTE_RE.search(p) for p in parts) else None


class Provider:
    id = ""
    label = ""
    homepage = ""
    description = ""
    region = "Worldwide"
    fields: tuple[CredField, ...] = ()
    feed = False  # True: results are not query specific; they are filtered locally after caching
    max_queries = 2
    cache_minutes = 30

    # ---- credentials ---------------------------------------------------------------------------
    def missing(self, creds: dict[str, str]) -> list[str]:
        return [f.label for f in self.fields if not f.optional and not creds.get(f.id)]

    @property
    def needs_key(self) -> bool:
        return any(not f.optional for f in self.fields)

    # ---- caching / API -------------------------------------------------------------------------
    def cache_key(self, q: SearchQuery) -> str:
        if self.feed:
            return "feed"
        return json.dumps([q.keywords[: self.max_queries], q.location, q.remote_only, q.country, q.limit])

    def fetch(self, http: HttpClient, q: SearchQuery, creds: dict[str, str]) -> list[Posting]:
        raise NotImplementedError

    def parse(self, payload: Any) -> list[Posting]:
        raise NotImplementedError

    # ---- helpers -------------------------------------------------------------------------------
    def _safe(self, items: Any, one: Callable[[dict], Optional[Posting]]) -> list[Posting]:
        out: list[Posting] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            try:
                p = one(item)
            except Exception:  # one malformed listing must not drop the others
                log.debug("%s: skipped a malformed listing", self.id, exc_info=True)
                continue
            if p and p.title and p.url:
                out.append(p)
        return out

    def _multi(self, q: SearchQuery, one: Callable[[str], list[Posting]]) -> list[Posting]:
        results: dict[str, Posting] = {}
        error: Optional[ProviderError] = None
        for kw in q.keywords[: self.max_queries] or [""]:
            try:
                for p in one(kw):
                    results.setdefault(p.external_id, p)
            except ProviderError as exc:
                error = exc
        if not results and error:
            raise error
        return list(results.values())


# ======================================================================================== no key
class Remotive(Provider):
    id, label = "remotive", "Remotive"
    homepage = "https://remotive.com/api-documentation"
    description = "Remote jobs worldwide. Free, no key."
    max_queries = 1  # the service asks for very few requests
    cache_minutes = 360

    def fetch(self, http, q, creds):
        params: dict[str, Any] = {"limit": q.limit}
        if q.primary():
            params["search"] = q.primary()
        return self.parse(http.request_json("GET", "https://remotive.com/api/remote-jobs", label=self.label, params=params))

    def parse(self, payload):
        def one(j):
            return Posting(
                source=self.id, external_id=str(j["id"]), title=clean_text(j.get("title")), url=j["url"],
                company=clean_text(j.get("company_name")) or None,
                location=clean_text(j.get("candidate_required_location")) or "Remote",
                remote=True, description=strip_html(j.get("description")),
                posted_at=parse_dt(j.get("publication_date")), salary=clean_text(j.get("salary")) or None,
                employment_type=(j.get("job_type") or "").replace("_", " ") or None,
                tags=as_list(j.get("tags")) + as_list(j.get("category")),
            )

        return self._safe((payload or {}).get("jobs"), one)


class Arbeitnow(Provider):
    id, label = "arbeitnow", "Arbeitnow"
    homepage = "https://www.arbeitnow.com/api"
    description = "Europe-focused and remote jobs. Free, no key."
    region = "Europe / remote"
    feed = True
    cache_minutes = 45

    def fetch(self, http, q, creds):
        out: list[Posting] = []
        for page in (1, 2):
            try:
                payload = http.request_json("GET", "https://www.arbeitnow.com/api/job-board-api", label=self.label, params={"page": page})
            except ProviderError:
                if out:
                    break
                raise
            out += self.parse(payload)
        return out

    def parse(self, payload):
        def one(j):
            return Posting(
                source=self.id, external_id=str(first(j, "slug", "url")), title=clean_text(j.get("title")), url=j["url"],
                company=clean_text(j.get("company_name")) or None, location=clean_text(j.get("location")) or None,
                remote=True if j.get("remote") else None, description=strip_html(j.get("description")),
                posted_at=parse_dt(j.get("created_at")), employment_type=", ".join(as_list(j.get("job_types"))) or None,
                tags=as_list(j.get("tags")),
            )

        return self._safe((payload or {}).get("data"), one)


class RemoteOK(Provider):
    id, label = "remoteok", "Remote OK"
    homepage = "https://remoteok.com/api"
    description = "Remote tech jobs, newest 100 postings. Free, no key."
    feed = True
    cache_minutes = 60

    def fetch(self, http, q, creds):
        return self.parse(http.request_json("GET", "https://remoteok.com/api", label=self.label))

    def parse(self, payload):
        items = [j for j in (payload or []) if isinstance(j, dict) and j.get("position")]  # element 0 is legal notice

        def one(j):
            return Posting(
                source=self.id, external_id=str(first(j, "id", "slug")), title=clean_text(j.get("position")),
                url=first(j, "url", "apply_url"), company=clean_text(j.get("company")) or None,
                location=clean_text(j.get("location")) or "Remote", remote=True,
                description=strip_html(j.get("description")), posted_at=parse_dt(j.get("date") or j.get("epoch")),
                salary=money(j.get("salary_min"), j.get("salary_max"), "USD", "year"), tags=as_list(j.get("tags")),
            )

        return self._safe(items, one)


class Jobicy(Provider):
    id, label = "jobicy", "Jobicy"
    homepage = "https://jobicy.com/jobs-rss-feed"
    description = "Remote jobs worldwide. Free, no key."
    cache_minutes = 90  # service asks for no more than hourly polling

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"count": min(q.limit, 100)}
            kw = kw.strip()
            if 3 <= len(kw) <= 50:
                params["tag"] = kw
            return self.parse(http.request_json("GET", "https://jobicy.com/api/v2/remote-jobs", label=self.label, params=params))

        return self._multi(q, one)

    def parse(self, payload):
        def one(j):
            return Posting(
                source=self.id, external_id=str(j["id"]), title=clean_text(j.get("jobTitle")), url=j["url"],
                company=clean_text(j.get("companyName")) or None, location=clean_text(j.get("jobGeo")) or "Remote",
                remote=True, description=strip_html(first(j, "jobDescription", "jobExcerpt", default="")),
                posted_at=parse_dt(j.get("pubDate")),
                salary=money(j.get("salaryMin"), j.get("salaryMax"), j.get("salaryCurrency"), j.get("salaryPeriod")),
                employment_type=", ".join(as_list(j.get("jobType"))) or None,
                tags=as_list(j.get("jobIndustry")) + ([j["jobLevel"]] if j.get("jobLevel") not in (None, "", "Any") else []),
            )

        return self._safe((payload or {}).get("jobs"), one)


class TheMuse(Provider):
    id, label = "themuse", "The Muse"
    homepage = "https://www.themuse.com/developers/api/v2"
    description = "Curated jobs, mostly US. Free; an optional key raises the rate limit."
    region = "US / remote"
    fields = (CredField("api_key", "The Muse API key (optional)", "MUSE_API_KEY", optional=True),)
    feed = True
    cache_minutes = 60

    LEVELS = {"entry": "Entry Level", "mid": "Mid Level", "senior": "Senior Level"}

    def cache_key(self, q):
        return json.dumps(["feed", q.level, q.location if not q.remote_only else "remote"])

    def fetch(self, http, q, creds):
        out: list[Posting] = []
        for page in (1, 2, 3):
            params: dict[str, Any] = {"page": page}
            if q.level in self.LEVELS:
                params["level"] = self.LEVELS[q.level]
            if q.remote_only:
                params["location"] = "Flexible / Remote"
            elif q.location:
                params["location"] = q.location
            if creds.get("api_key"):
                params["api_key"] = creds["api_key"]
            try:
                payload = http.request_json("GET", "https://www.themuse.com/api/public/jobs", label=self.label, params=params)
            except ProviderError:
                if out:
                    break
                raise
            out += self.parse(payload)
        return out

    def parse(self, payload):
        def one(j):
            locs = [x.get("name", "") for x in j.get("locations", []) if isinstance(x, dict)]
            levels = [x.get("name", "") for x in j.get("levels", []) if isinstance(x, dict)]
            cats = [x.get("name", "") for x in j.get("categories", []) if isinstance(x, dict)]
            return Posting(
                source=self.id, external_id=str(j["id"]), title=clean_text(j.get("name")),
                url=(j.get("refs") or {}).get("landing_page", ""),
                company=clean_text((j.get("company") or {}).get("name")) or None,
                location="; ".join(l for l in locs if l) or None,
                remote=True if any("remote" in l.lower() or "flexible" in l.lower() for l in locs) else None,
                description=strip_html(j.get("contents")), posted_at=parse_dt(j.get("publication_date")),
                tags=[t for t in cats + levels if t],
            )

        return self._safe((payload or {}).get("results"), one)


class Himalayas(Provider):
    id, label = "himalayas", "Himalayas"
    homepage = "https://himalayas.app/docs/remote-jobs-api"
    description = "Remote jobs worldwide. Free, no key (shared public rate limit)."
    cache_minutes = 60

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"page": 1}
            if kw:
                params["q"] = kw
            return self.parse(http.request_json("GET", "https://himalayas.app/jobs/api/search", label=self.label, params=params))

        return self._multi(q, one)

    def parse(self, payload):
        def one(j):
            link = j.get("applicationLink") or ""
            restr = as_list(j.get("locationRestrictions"))
            return Posting(
                source=self.id, external_id=str(first(j, "guid", "applicationLink")), title=clean_text(j.get("title")),
                url=link, company=clean_text(j.get("companyName")) or None,
                location=", ".join(restr) if restr else "Worldwide (remote)", remote=True,
                description=strip_html(first(j, "description", "excerpt", default="")), posted_at=parse_dt(j.get("pubDate")),
                salary=money(j.get("minSalary"), j.get("maxSalary"), j.get("currency"), j.get("salaryPeriod")),
                employment_type=j.get("employmentType"), tags=as_list(j.get("categories")) + as_list(j.get("seniority")),
            )

        return self._safe((payload or {}).get("jobs"), one)


# ====================================================================================== API keys
class Adzuna(Provider):
    id, label = "adzuna", "Adzuna"
    homepage = "https://developer.adzuna.com/"
    description = "Large aggregator (India, UK, US and more). Free key."
    region = "Country based (see Settings)"
    fields = (CredField("app_id", "Adzuna app id", "ADZUNA_APP_ID", secret=False), CredField("app_key", "Adzuna app key", "ADZUNA_APP_KEY"))
    cache_minutes = 30

    def fetch(self, http, q, creds):
        country = (q.country or "in").lower()

        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {
                "app_id": creds["app_id"], "app_key": creds["app_key"], "results_per_page": min(q.limit, 50),
                "content-type": "application/json", "max_days_old": q.max_age_days,
            }
            if kw:
                params["what"] = kw
            where = "" if q.remote_only else q.location
            if where:
                params["where"] = where
            if q.remote_only:
                params["what"] = f"{kw} remote".strip()
            return self.parse(http.request_json("GET", f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", label=self.label, params=params))

        return self._multi(q, one)

    def parse(self, payload):
        def one(j):
            title = clean_text(j.get("title"))
            desc = strip_html(j.get("description"))
            loc = clean_text((j.get("location") or {}).get("display_name")) or None
            return Posting(
                source=self.id, external_id=str(j["id"]), title=title, url=j.get("redirect_url", ""),
                company=clean_text((j.get("company") or {}).get("display_name")) or None, location=loc,
                remote=_is_remote_text(title, desc, loc), description=desc, posted_at=parse_dt(j.get("created")),
                salary=money(j.get("salary_min"), j.get("salary_max")) if not j.get("salary_is_predicted") in (1, "1", True) else None,
                employment_type=" ".join(x for x in (j.get("contract_time"), j.get("contract_type")) if x).replace("_", " ") or None,
                tags=as_list((j.get("category") or {}).get("label")),
            )

        return self._safe((payload or {}).get("results"), one)


class Jooble(Provider):
    id, label = "jooble", "Jooble"
    homepage = "https://jooble.org/api/about"
    description = "Global aggregator. Free key (one key per country site)."
    fields = (CredField("api_key", "Jooble API key", "JOOBLE_API_KEY"),)
    cache_minutes = 30

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            body = {
                "keywords": kw or "", "page": 1, "ResultOnPage": min(q.limit, 50),
                "location": "" if q.remote_only else (q.location or COUNTRY_NAMES.get(q.country, "")),
            }
            if q.remote_only:
                body["keywords"] = f"{kw} remote".strip()
            return self.parse(http.request_json("POST", f"https://jooble.org/api/{creds['api_key']}", label=self.label, json=body))

        return self._multi(q, one)

    def parse(self, payload):
        def one(j):
            title, snip, loc = clean_text(j.get("title")), strip_html(j.get("snippet")), clean_text(j.get("location")) or None
            return Posting(
                source=self.id, external_id=str(first(j, "id", "link")), title=title, url=j.get("link", ""),
                company=clean_text(j.get("company")) or None, location=loc, remote=_is_remote_text(title, loc, snip),
                description=snip, posted_at=parse_dt(j.get("updated")), salary=clean_text(j.get("salary")) or None,
                employment_type=clean_text(j.get("type")) or None,
            )

        return self._safe((payload or {}).get("jobs"), one)


class Reed(Provider):
    id, label = "reed", "Reed (UK)"
    homepage = "https://www.reed.co.uk/developers/jobseeker"
    description = "UK jobs. Free key."
    region = "United Kingdom"
    fields = (CredField("api_key", "Reed API key", "REED_API_KEY"),)
    cache_minutes = 30

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"keywords": kw, "resultsToTake": min(q.limit, 100)}
            if q.location and not q.remote_only:
                params["locationName"] = q.location
            if q.remote_only:
                params["keywords"] = f"{kw} remote".strip()
            return self.parse(http.request_json("GET", "https://www.reed.co.uk/api/1.0/search", label=self.label, params=params, auth=(creds["api_key"], "")))

        return self._multi(q, one)

    def parse(self, payload):
        def one(j):
            title, desc, loc = clean_text(j.get("jobTitle")), strip_html(j.get("jobDescription")), clean_text(j.get("locationName")) or None
            return Posting(
                source=self.id, external_id=str(j["jobId"]), title=title, url=first(j, "jobUrl", default=f"https://www.reed.co.uk/jobs/{j['jobId']}"),
                company=clean_text(j.get("employerName")) or None, location=loc, remote=_is_remote_text(title, loc, desc),
                description=desc, posted_at=parse_dt(j.get("date")),
                salary=money(j.get("minimumSalary"), j.get("maximumSalary"), j.get("currency") or "GBP", "year"),
            )

        return self._safe((payload or {}).get("results"), one)


class UsaJobs(Provider):
    id, label = "usajobs", "USAJOBS"
    homepage = "https://developer.usajobs.gov/"
    description = "US federal government jobs. Free key (registered e-mail required)."
    region = "United States"
    fields = (CredField("api_key", "USAJOBS API key", "USAJOBS_API_KEY"), CredField("email", "E-mail used to request the key", "USAJOBS_EMAIL", secret=False))
    cache_minutes = 30

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"Keyword": kw, "ResultsPerPage": min(q.limit, 50), "DatePosted": min(q.max_age_days, 60)}
            if q.location and not q.remote_only:
                params["LocationName"] = q.location
            if q.remote_only:
                params["RemoteIndicator"] = "True"
            headers = {"User-Agent": creds["email"], "Authorization-Key": creds["api_key"]}
            return self.parse(http.request_json("GET", "https://data.usajobs.gov/api/Search", label=self.label, params=params, headers=headers))

        return self._multi(q, one)

    def parse(self, payload):
        items = ((payload or {}).get("SearchResult") or {}).get("SearchResultItems") or []

        def one(item):
            d = item.get("MatchedObjectDescriptor") or {}
            details = (d.get("UserArea") or {}).get("Details") or {}
            rem = (d.get("PositionRemuneration") or [{}])[0]
            apply_uri = (d.get("ApplyURI") or [None])[0]
            sched = ((d.get("PositionSchedule") or [{}])[0]).get("Name")
            loc = clean_text(d.get("PositionLocationDisplay")) or None
            desc = "\n".join(x for x in (strip_html(details.get("JobSummary")), strip_html(d.get("QualificationSummary"))) if x)
            return Posting(
                source=self.id, external_id=str(first(d, "PositionID", "MatchedObjectId", default=item.get("MatchedObjectId"))),
                title=clean_text(d.get("PositionTitle")), url=first(d, "PositionURI", default=apply_uri),
                company=clean_text(d.get("OrganizationName")) or None, location=loc,
                remote=_is_remote_text(d.get("PositionTitle"), loc), description=desc,
                posted_at=parse_dt(d.get("PublicationStartDate")),
                salary=money(rem.get("MinimumRange"), rem.get("MaximumRange"), "USD", (rem.get("Description") or "").lower() or None),
                employment_type=sched,
            )

        return self._safe(items, one)


def _jsearch_parse(self: Provider, payload: Any) -> list[Posting]:
    data = (payload or {}).get("data")
    if isinstance(data, dict):  # some versions nest the list
        data = data.get("jobs") or data.get("results")

    def one(j):
        loc = j.get("job_location") or ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x) or None
        desc = strip_html(j.get("job_description"))
        hl = j.get("job_highlights") or {}
        extra = "\n".join(f"- {x}" for k in ("Qualifications", "Responsibilities") for x in (hl.get(k) or []))
        return Posting(
            source=self.id, external_id=str(first(j, "job_id", "job_apply_link")), title=clean_text(j.get("job_title")),
            url=first(j, "job_apply_link", "job_google_link", default=""), company=clean_text(j.get("employer_name")) or None,
            location=loc, remote=True if j.get("job_is_remote") else None, description=(desc + ("\n" + extra if extra and extra not in desc else "")).strip(),
            posted_at=parse_dt(j.get("job_posted_at_datetime_utc")),
            salary=money(j.get("job_min_salary"), j.get("job_max_salary"), j.get("job_salary_currency"), j.get("job_salary_period")),
            employment_type=j.get("job_employment_type"), tags=[j["job_publisher"]] if j.get("job_publisher") else [],
        )

    return self._safe(data, one)


def _jsearch_query(kw: str, q: SearchQuery) -> str:
    place = "" if q.remote_only else q.location
    return f"{kw} in {place}" if place else kw


class JSearchNinja(Provider):
    id, label = "jsearch", "JSearch (Google Jobs)"
    homepage = "https://openwebninja.com/api/jsearch"
    description = "Google-for-Jobs style aggregator (LinkedIn, Indeed, Glassdoor ...). Key required, free tier."
    fields = (CredField("api_key", "OpenWeb Ninja API key", "JSEARCH_API_KEY"),)
    cache_minutes = 60
    parse = _jsearch_parse

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"query": _jsearch_query(kw, q), "country": q.country, "date_posted": "month"}
            if q.remote_only:
                params["work_from_home"] = "true"
            return self.parse(http.request_json("GET", "https://api.openwebninja.com/jsearch/search-v2", label=self.label, params=params, headers={"x-api-key": creds["api_key"]}))

        return self._multi(q, one)


class JSearchRapid(Provider):
    id, label = "jsearch_rapidapi", "JSearch via RapidAPI"
    homepage = "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch"
    description = "Same JSearch data through a RapidAPI subscription. Key required."
    fields = (CredField("api_key", "RapidAPI key", "RAPIDAPI_KEY"),)
    cache_minutes = 60
    parse = _jsearch_parse

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"query": _jsearch_query(kw, q), "page": 1, "num_pages": 1, "country": q.country, "date_posted": "month"}
            if q.remote_only:
                params["remote_jobs_only"] = "true"
            headers = {"X-RapidAPI-Key": creds["api_key"], "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
            return self.parse(http.request_json("GET", "https://jsearch.p.rapidapi.com/search", label=self.label, params=params, headers=headers))

        return self._multi(q, one)


class Findwork(Provider):
    id, label = "findwork", "Findwork"
    homepage = "https://findwork.dev/developers/"
    description = "Software and tech jobs. Free key."
    fields = (CredField("api_key", "Findwork API key", "FINDWORK_API_KEY"),)
    cache_minutes = 30

    def fetch(self, http, q, creds):
        def one(kw: str) -> list[Posting]:
            params: dict[str, Any] = {"search": kw, "sort_by": "date"}
            if q.location and not q.remote_only:
                params["location"] = q.location
            if q.remote_only:
                params["remote"] = "true"
            return self.parse(http.request_json("GET", "https://findwork.dev/api/jobs/", label=self.label, params=params, headers={"Authorization": f"Token {creds['api_key']}"}))

        return self._multi(q, one)

    def parse(self, payload):
        def one(j):
            return Posting(
                source=self.id, external_id=str(j["id"]), title=clean_text(j.get("role")), url=j.get("url", ""),
                company=clean_text(j.get("company_name")) or None, location=clean_text(j.get("location")) or None,
                remote=True if j.get("remote") else None, description=strip_html(j.get("text")),
                posted_at=parse_dt(j.get("date_posted")), employment_type=clean_text(j.get("employment_type")) or None,
                tags=as_list(j.get("keywords")),
            )

        return self._safe((payload or {}).get("results"), one)


def all_providers() -> list[Provider]:
    """Keyless sources first (they work out of the box), then key-based ones."""
    return [
        Remotive(), Arbeitnow(), RemoteOK(), Jobicy(), TheMuse(), Himalayas(),
        Adzuna(), Jooble(), JSearchNinja(), JSearchRapid(), Reed(), UsaJobs(), Findwork(),
    ]

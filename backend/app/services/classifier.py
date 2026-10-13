"""Classify what's on screen as focus, neutral, or distracting.

Pure functions only (no database, no I/O), so the rules are easy to test and reason about.

Decision order, first match wins:
1. The user's own rules. If several match, the longest (most specific) pattern wins.
2. The session intent: a window title that shares meaningful words with what the user said
   they're working on counts as focus ("Linear algebra" vs "Linear Algebra - 3Blue1Brown - YouTube").
3. Built-in knowledge of common sites and apps. YouTube is judged by the video title.
4. Anything else is neutral: unknown apps never raise false alarms.
"""

import re
from dataclasses import dataclass

from app.models.activity import ActivityCategory as Category


@dataclass(frozen=True)
class Classification:
    category: Category
    # What the user is on, in human terms ("YouTube", "Visual Studio Code"). Used for stats and "always allow".
    subject: str
    reason: str


@dataclass(frozen=True)
class UserRule:
    pattern: str  # lowercase substring matched against "app | title"
    kind: str  # "focus" or "distraction"


# ---------------------------------------------------------------------------
# Window title parsing
# ---------------------------------------------------------------------------

# Browser executables (Windows) and app names (macOS/Linux), lowercase.
BROWSER_APPS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe",
    "google chrome", "microsoft edge", "firefox", "safari", "brave browser", "opera", "vivaldi", "arc", "chromium",
}  # fmt: skip

# Suffixes browsers append to page titles, longest first.
BROWSER_TITLE_SUFFIXES = (
    "google chrome", "microsoft edge", "mozilla firefox", "firefox", "brave", "opera", "vivaldi", "chromium", "safari",
)  # fmt: skip

# Edge appends things like "and 3 more pages - Personal - Microsoft Edge"; strip profile/tab-count noise.
_EDGE_NOISE = re.compile(r"\s+and \d+ more pages?\b.*$", re.IGNORECASE)


def _normalize(text: str) -> str:
    # Some browsers insert zero-width characters (e.g. "Microsoft​ Edge").
    return re.sub(r"[​-‏﻿]", "", text or "").strip()


def page_title(app: str, title: str) -> str:
    """The page title without the browser's name (for browsers); the window title otherwise."""
    text = _normalize(title)
    if app.lower() not in BROWSER_APPS:
        return text
    parts = [p.strip() for p in re.split(r"\s+[-–—]\s+", text)]
    while len(parts) > 1 and any(parts[-1].lower().startswith(s) for s in BROWSER_TITLE_SUFFIXES):
        parts.pop()
    while len(parts) > 1 and parts[-1].lower() in {"personal", "work", "profile 1", "default"}:
        parts.pop()  # browser profile names
    return _EDGE_NOISE.sub("", " - ".join(parts)).strip()


# ---------------------------------------------------------------------------
# Built-in knowledge
# ---------------------------------------------------------------------------

# (pattern matched with word boundaries against the page/window title, subject label)
FOCUS_SITES = [
    ("coursera", "Coursera"), ("khan academy", "Khan Academy"), ("edx", "edX"), ("udemy", "Udemy"),
    ("udacity", "Udacity"), ("brilliant", "Brilliant"), ("codecademy", "Codecademy"), ("leetcode", "LeetCode"),
    ("hackerrank", "HackerRank"), ("stack overflow", "Stack Overflow"), ("github", "GitHub"), ("gitlab", "GitLab"),
    ("mdn web docs", "MDN"), ("w3schools", "W3Schools"), ("geeksforgeeks", "GeeksforGeeks"),
    ("python.org", "Python docs"), ("documentation", "Documentation"), ("docs", "Documentation"),
    ("overleaf", "Overleaf"), ("google docs", "Google Docs"), ("google sheets", "Google Sheets"),
    ("google slides", "Google Slides"), ("notion", "Notion"), ("wolfram", "Wolfram Alpha"), ("desmos", "Desmos"),
    ("arxiv", "arXiv"), ("google scholar", "Google Scholar"), ("jupyter", "Jupyter"), ("colab", "Google Colab"),
    ("kaggle", "Kaggle"), ("quizlet", "Quizlet"), ("anki", "Anki"), ("duolingo", "Duolingo"),
    ("mit opencourseware", "MIT OpenCourseWare"), ("canvas", "Canvas"), ("moodle", "Moodle"),
    ("blackboard", "Blackboard"),
]  # fmt: skip

DISTRACTING_SITES = [
    ("instagram", "Instagram"), ("facebook", "Facebook"), ("tiktok", "TikTok"), ("twitter", "X (Twitter)"),
    ("/ x", "X (Twitter)"), ("reddit", "Reddit"), ("netflix", "Netflix"), ("prime video", "Prime Video"),
    ("disney+", "Disney+"), ("hulu", "Hulu"), ("hotstar", "Hotstar"), ("twitch", "Twitch"),
    ("9gag", "9GAG"), ("pinterest", "Pinterest"), ("tumblr", "Tumblr"), ("snapchat", "Snapchat"),
    ("amazon.", "Amazon shopping"), ("flipkart", "Flipkart"), ("ebay", "eBay"), ("espn", "ESPN"),
    ("cricbuzz", "Cricbuzz"), ("whatsapp", "WhatsApp"), ("messenger", "Messenger"), ("crunchyroll", "Crunchyroll"),
]  # fmt: skip

# Matched against the executable / app name.
FOCUS_APPS = {
    "code.exe": "Visual Studio Code", "visual studio code": "Visual Studio Code", "code": "Visual Studio Code",
    "cursor.exe": "Cursor", "pycharm64.exe": "PyCharm", "pycharm": "PyCharm", "idea64.exe": "IntelliJ IDEA",
    "intellij idea": "IntelliJ IDEA", "devenv.exe": "Visual Studio", "sublime_text.exe": "Sublime Text",
    "notepad++.exe": "Notepad++", "windowsterminal.exe": "Terminal", "terminal": "Terminal", "iterm2": "Terminal",
    "powershell.exe": "Terminal", "pwsh.exe": "Terminal", "cmd.exe": "Terminal", "winword.exe": "Microsoft Word",
    "microsoft word": "Microsoft Word", "excel.exe": "Microsoft Excel", "microsoft excel": "Microsoft Excel",
    "powerpnt.exe": "PowerPoint", "microsoft powerpoint": "PowerPoint", "onenote.exe": "OneNote",
    "notion.exe": "Notion", "notion": "Notion", "obsidian.exe": "Obsidian", "obsidian": "Obsidian",
    "acrobat.exe": "PDF reader", "acrord32.exe": "PDF reader", "sumatrapdf.exe": "PDF reader", "preview": "Preview",
    "rstudio.exe": "RStudio", "matlab.exe": "MATLAB", "anki.exe": "Anki", "zotero.exe": "Zotero",
}  # fmt: skip

DISTRACTING_APPS = {
    "steam.exe": "Steam", "steam": "Steam", "epicgameslauncher.exe": "Epic Games", "discord.exe": "Discord",
    "discord": "Discord", "whatsapp.exe": "WhatsApp", "whatsapp": "WhatsApp", "telegram.exe": "Telegram",
    "telegram": "Telegram", "netflix.exe": "Netflix", "instagram.exe": "Instagram", "tiktok.exe": "TikTok",
    "riotclientservices.exe": "Riot Games", "leagueclient.exe": "League of Legends", "robloxplayerbeta.exe": "Roblox",
    "minecraft.exe": "Minecraft", "javaw.exe": "Minecraft",
}  # fmt: skip

# System UI and FlowSense itself: never a distraction, never focus.
NEUTRAL_APPS = {
    "explorer.exe", "finder", "lockapp.exe", "searchhost.exe", "shellexperiencehost.exe", "startmenuexperiencehost.exe",
    "taskmgr.exe", "systemsettings.exe", "applicationframehost.exe", "loginwindow", "dock", "systemuiserver",
}  # fmt: skip

# YouTube videos whose titles contain these count as study material.
STUDY_KEYWORDS = [
    "lecture", "tutorial", "course", "lesson", "class", "explained", "explanation", "how to", "introduction",
    "intro to", "crash course", "learn", "study", "chapter", "exam", "revision", "solution", "solved", "problem set",
    "math", "calculus", "algebra", "geometry", "statistics", "probability", "physics", "chemistry", "biology",
    "programming", "python", "javascript", "java", "c++", "algorithm", "data structure", "machine learning",
    "deep learning", "neural network", "economics", "accounting", "history", "documentary", "opencourseware",
    "khan academy", "3blue1brown", "freecodecamp", "cs50", "mit", "stanford", "harvard", "nptel",
]  # fmt: skip

STOPWORDS = {
    "about", "after", "also", "been", "from", "have", "into", "just", "more", "most", "only", "over", "some", "than",
    "that", "their", "them", "then", "there", "these", "they", "this", "what", "when", "which", "while", "will",
    "with", "work", "working", "your", "youtube", "video", "videos", "google", "chrome", "edge", "firefox", "page",
    "home", "watch", "official", "part", "episode", "full",
}  # fmt: skip


def _contains(text: str, pattern: str) -> bool:
    """Case-insensitive match of `pattern` in `text` at word boundaries (where the pattern starts/ends with a word)."""
    escaped = re.escape(pattern.lower())
    left = r"\b" if pattern[:1].isalnum() else ""
    right = r"\b" if pattern[-1:].isalnum() else ""
    return re.search(f"{left}{escaped}{right}", text.lower()) is not None


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if len(w) >= 4 and w not in STOPWORDS}


def _is_youtube(app: str, title: str, page: str) -> bool:
    return app.lower() in BROWSER_APPS and (_contains(title, "youtube") or page.lower() == "youtube")


def _youtube_video_title(page: str) -> str:
    # "Video title - YouTube" -> "Video title"; a leading "(3) " notification count is dropped too.
    video = re.sub(r"\s+[-–—]\s+youtube$", "", page, flags=re.IGNORECASE).strip()
    return re.sub(r"^\(\d+\)\s*", "", video)


def classify(app: str, title: str, intent: str | None = None, rules: list[UserRule] | tuple = ()) -> Classification:
    app_name = (app or "").strip()
    app_key = app_name.lower()
    title = _normalize(title)
    page = page_title(app_name, title)
    haystack = f"{app_key} | {title.lower()}"
    app_label = FOCUS_APPS.get(app_key) or DISTRACTING_APPS.get(app_key) or app_name or "Unknown app"

    # 1. User rules, most specific first.
    matches = [rule for rule in rules if rule.pattern and rule.pattern.lower() in haystack]
    if matches:
        rule = max(matches, key=lambda r: len(r.pattern))
        category = Category.FOCUS if rule.kind == "focus" else Category.DISTRACTING
        verb = "allowed" if category == Category.FOCUS else "blocked"
        return Classification(category, rule.pattern, f'You {verb} "{rule.pattern}"')

    if app_key in NEUTRAL_APPS or title.lower().startswith("flowsense"):
        return Classification(Category.NEUTRAL, app_label, "System or FlowSense window")

    # 2. Matches what the user said they're working on.
    if intent:
        shared = _keywords(intent) & _keywords(page)
        if shared:
            subject = "YouTube" if _is_youtube(app_name, title, page) else (page[:60] or app_label)
            return Classification(
                Category.FOCUS, subject, f"Matches what you're working on ({', '.join(sorted(shared))})"
            )

    # 3. Built-in knowledge.
    if _is_youtube(app_name, title, page):
        video = _youtube_video_title(page)
        if video.lower() in {"", "youtube"}:
            return Classification(Category.DISTRACTING, "YouTube", "Browsing the YouTube feed")
        hits = [keyword for keyword in STUDY_KEYWORDS if _contains(video, keyword)]
        if hits:
            return Classification(Category.FOCUS, "YouTube", f"Looks like a study video ({hits[0]})")
        return Classification(Category.DISTRACTING, "YouTube", "YouTube video unrelated to your session")

    if app_key in BROWSER_APPS:
        for pattern, label in DISTRACTING_SITES:
            if _contains(page, pattern):
                return Classification(Category.DISTRACTING, label, f"{label} is usually a distraction")
        for pattern, label in FOCUS_SITES:
            if _contains(page, pattern):
                return Classification(Category.FOCUS, label, f"{label} is a study/work site")
        site = re.split(r"\s+[-–—|]\s+", page)[-1].strip() if page else ""
        return Classification(Category.NEUTRAL, (site or "Web browser")[:60], "Website not in any list")

    if app_key in FOCUS_APPS:
        return Classification(Category.FOCUS, app_label, f"{app_label} is a work app")
    if app_key in DISTRACTING_APPS:
        return Classification(Category.DISTRACTING, app_label, f"{app_label} is usually a distraction")
    return Classification(Category.NEUTRAL, app_label, "App not in any list")

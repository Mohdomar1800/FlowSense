"""Classifier unit tests (pure function, no database)."""

import pytest

from app.services.classifier import Category, UserRule, classify, page_title

CHROME = "chrome.exe"
EDGE = "msedge.exe"


@pytest.mark.parametrize(
    ("app", "title", "expected"),
    [
        (CHROME, "Funny cats - YouTube - Google Chrome", "Funny cats - YouTube"),
        (EDGE, "Lecture 5 - YouTube and 3 more pages - Personal - Microsoft​ Edge", "Lecture 5 - YouTube"),
        ("firefox.exe", "Coursera | Online Courses — Mozilla Firefox", "Coursera | Online Courses"),
        ("code.exe", "main.py - FlowSense - Visual Studio Code", "main.py - FlowSense - Visual Studio Code"),
    ],
)
def test_page_title_strips_browser_noise(app, title, expected):
    assert page_title(app, title) == expected


@pytest.mark.parametrize(
    ("app", "title", "category", "subject"),
    [
        # YouTube depends on the video
        (CHROME, "MIT 18.06 Linear Algebra, Lecture 5 - YouTube - Google Chrome", Category.FOCUS, "YouTube"),
        (CHROME, "(3) Binary Search Explained in 10 Minutes - YouTube - Google Chrome", Category.FOCUS, "YouTube"),
        (EDGE, "Funny cats compilation 2026 - YouTube - Personal - Microsoft​ Edge", Category.DISTRACTING, "YouTube"),
        (CHROME, "YouTube - Google Chrome", Category.DISTRACTING, "YouTube"),
        # Sites
        (CHROME, "Machine Learning Specialization | Coursera - Google Chrome", Category.FOCUS, "Coursera"),
        (CHROME, "python - How do I sort a dict? - Stack Overflow - Google Chrome", Category.FOCUS, "Stack Overflow"),
        (CHROME, "Instagram - Google Chrome", Category.DISTRACTING, "Instagram"),
        (CHROME, "r/funny - Reddit - Google Chrome", Category.DISTRACTING, "Reddit"),
        (CHROME, "Home / X - Google Chrome", Category.DISTRACTING, "X (Twitter)"),
        (CHROME, "Weather forecast - Google Search - Google Chrome", Category.NEUTRAL, "Google Search"),
        # Apps
        ("Code.exe", "main.py - FlowSense - Visual Studio Code", Category.FOCUS, "Visual Studio Code"),
        ("WINWORD.EXE", "Essay draft.docx - Word", Category.FOCUS, "Microsoft Word"),
        ("Discord.exe", "#general | Study Group - Discord", Category.DISTRACTING, "Discord"),
        ("steam.exe", "Steam", Category.DISTRACTING, "Steam"),
        ("explorer.exe", "Downloads", Category.NEUTRAL, "explorer.exe"),
        ("pythonw.exe", "FlowSense", Category.NEUTRAL, "pythonw.exe"),
        ("someapp.exe", "Some window", Category.NEUTRAL, "someapp.exe"),
        ("", "", Category.NEUTRAL, "Unknown app"),
    ],
)
def test_builtin_classification(app, title, category, subject):
    result = classify(app, title)
    assert result.category == category, result
    assert result.subject == subject
    assert result.reason


def test_word_boundaries_prevent_false_matches():
    # "submit" must not count as "MIT", "classic" not as "class", "redditch" not as "reddit".
    assert classify(CHROME, "How to submit a form - YouTube - Google Chrome").category == Category.FOCUS  # "how to"
    assert classify(CHROME, "Classic rock playlist - YouTube - Google Chrome").category == Category.DISTRACTING
    assert classify(CHROME, "Redditch town news - Google Chrome").category == Category.NEUTRAL


def test_intent_makes_matching_content_focus():
    title = "Eigenvalues and eigenvectors | Chapter 14 - YouTube - Google Chrome"
    assert classify(CHROME, title).category == Category.FOCUS  # "chapter" is a study keyword anyway

    gaming_title = "Elden Ring speedrun analysis - YouTube - Google Chrome"
    assert classify(CHROME, gaming_title).category == Category.DISTRACTING
    with_intent = classify(CHROME, gaming_title, intent="Write my essay on Elden Ring speedrun culture")
    assert with_intent.category == Category.FOCUS
    assert "elden" in with_intent.reason

    # Generic words like "video" or "youtube" in the intent don't count as a match.
    assert (
        classify(CHROME, "Funny cats - YouTube - Google Chrome", intent="watch video").category == Category.DISTRACTING
    )


def test_user_rules_override_builtins_and_most_specific_wins():
    rules = [UserRule("discord", "focus"), UserRule("youtube", "distraction"), UserRule("lecture - youtube", "focus")]
    assert classify("Discord.exe", "Study Group - Discord", rules=rules).category == Category.FOCUS
    assert (
        classify(CHROME, "Calculus explained - YouTube - Google Chrome", rules=rules).category == Category.DISTRACTING
    )
    assert classify(CHROME, "Physics Lecture - YouTube - Google Chrome", rules=rules).category == Category.FOCUS

    allowed = classify("Discord.exe", "Study Group - Discord", rules=rules)
    assert allowed.reason == 'You allowed "discord"'
    assert allowed.subject == "discord"


def test_user_rules_beat_intent():
    rules = [UserRule("reddit", "distraction")]
    result = classify(CHROME, "r/learnpython - Reddit - Google Chrome", intent="learn python", rules=rules)
    assert result.category == Category.DISTRACTING

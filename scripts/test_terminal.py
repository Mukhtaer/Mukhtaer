import re
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from xml.sax.saxutils import escape

from terminal import QUOTES, THEMES, current_streak, longest_streak, quote_of_the_day, render, summarize, top_languages


def days(*counts, start=1):
    return [{"date": f"2026-10-{start + i:02d}", "contributionCount": c} for i, c in enumerate(counts)]


def repo(*pairs):
    return {"languages": {"edges": [{"size": size, "node": {"name": name, "color": "#000000"}} for name, size in pairs]}}


class StreakTest(unittest.TestCase):
    def test_counts_back_from_today(self):
        self.assertEqual(current_streak(days(1, 0, 2, 3, 4), date(2026, 10, 5)), 3)

    def test_today_without_contributions_keeps_yesterdays_streak(self):
        self.assertEqual(current_streak(days(0, 2, 3, 0), date(2026, 10, 4)), 2)

    def test_broken_streak_is_zero(self):
        self.assertEqual(current_streak(days(5, 0, 0), date(2026, 10, 3)), 0)

    def test_ignores_future_days(self):
        self.assertEqual(current_streak(days(1, 1, 0, 0), date(2026, 10, 2)), 2)

    def test_longest_run(self):
        self.assertEqual(longest_streak(days(1, 1, 0, 1, 1, 1, 0)), 3)


class LanguagesTest(unittest.TestCase):
    def test_merges_repos_without_filtering(self):
        result = top_languages([repo(("PHP", 300), ("C++", 900)), repo(("Dart", 100), ("PHP", 100))])
        self.assertEqual([(name, round(share, 4)) for name, _, share in result], [("C++", 0.6429), ("PHP", 0.2857), ("Dart", 0.0714)])

    def test_shares_are_relative_to_shown_languages(self):
        result = top_languages([repo(("A", 4), ("B", 3), ("D", 2), ("E", 1))], limit=2)
        self.assertEqual([name for name, _, _ in result], ["A", "B"])
        self.assertAlmostEqual(sum(share for _, _, share in result), 1.0)

    def test_shows_top_eight_by_default(self):
        result = top_languages([repo(*((f"L{i}", 10 - i) for i in range(9)))])
        self.assertEqual([name for name, _, _ in result], [f"L{i}" for i in range(8)])

    def test_no_languages(self):
        self.assertEqual(top_languages([repo()]), [])


class QuoteTest(unittest.TestCase):
    def test_same_day_same_quote(self):
        self.assertEqual(quote_of_the_day(date(2026, 10, 9)), quote_of_the_day(date(2026, 10, 9)))

    def test_rotates_across_days(self):
        picks = {quote_of_the_day(date.fromordinal(date(2026, 1, 1).toordinal() + i)) for i in range(60)}
        self.assertGreater(len(picks), len(QUOTES) // 2)


class RenderTest(unittest.TestCase):
    def test_renders_valid_svg_with_stats(self):
        user = {
            "contributionsCollection": {"contributionCalendar": {
                "totalContributions": 1234,
                "weeks": [{"contributionDays": [
                    {"date": "2026-10-01", "contributionCount": 2, "contributionLevel": "SECOND_QUARTILE"},
                    {"date": "2026-10-02", "contributionCount": 0, "contributionLevel": "NONE"},
                ]}],
            }},
            "repositories": {"nodes": [repo(("PHP", 3), ("Dart", 1))]},
        }
        stats = summarize(user, date(2026, 10, 2))
        for theme in THEMES.values():
            svg = render(stats, theme, "2 Oct 2026")
            ET.fromstring(svg)
            self.assertIn("1,234", svg)
            self.assertIn("75.00%", svg)
            self.assertIn("synced 2 Oct 2026", svg)
            self.assertIn(escape(stats["quote"][1]), svg)
            self.assertNotIn("\u2014", svg)
            self.assertIn("font/woff2;base64,", svg)
            self.assertLess(svg.index(">next.js<"), svg.index(">flutter<"))
            self.assertIn("python", svg)
            self.assertLess(max(float(b) for b in re.findall(r'begin="([\d.]+)s"', svg)), 6)
            for dropped in ("node", "express", "mongodb"):
                self.assertNotIn(dropped, svg)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from src.terminal_ui import TerminalUI


class TerminalUITests(unittest.TestCase):
    def test_width_respects_narrow_terminal(self) -> None:
        ui = TerminalUI(output_stream=io.StringIO(), input_stream=io.StringIO())
        with patch("src.terminal_ui.shutil.get_terminal_size", return_value=os.terminal_size((60, 20))):
            self.assertEqual(ui._width(), 60)

    def test_wrap_breaks_long_unspaced_tokens(self) -> None:
        ui = TerminalUI(output_stream=io.StringIO(), input_stream=io.StringIO())
        text = "/this/is/a/very/long/path/" + ("a" * 180)
        wrapped = ui._wrap_preserving_paragraphs(text, 20)
        self.assertTrue(wrapped)
        self.assertTrue(all(len(line) <= 20 for line in wrapped))

    def test_choose_action_uses_custom_input_stream(self) -> None:
        output_stream = io.StringIO()
        input_stream = io.StringIO("5\n")
        ui = TerminalUI(output_stream=output_stream, input_stream=input_stream)

        choice = ui.choose_action(["Refine A", "Refine B", "Refine C"])

        self.assertEqual(choice, "5")
        self.assertIn("Enter your choice:", output_stream.getvalue())

    def test_read_multiline_feedback_uses_custom_input_stream(self) -> None:
        ui = TerminalUI(
            output_stream=io.StringIO(),
            input_stream=io.StringIO("First line\nSecond line\n\n"),
        )

        feedback = ui.read_multiline_feedback()

        self.assertEqual(feedback, "First line\nSecond line")


if __name__ == "__main__":
    unittest.main()

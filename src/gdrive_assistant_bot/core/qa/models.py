from __future__ import annotations

from typing import Literal

# Kinds of answers returned by QAService.
QAAnswerKind = Literal["empty", "fragments", "llm"]

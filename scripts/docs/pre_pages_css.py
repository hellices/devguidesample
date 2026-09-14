"""Token-aware inline CSS subset for preservation visibility checks."""

from __future__ import annotations

from scripts.docs.pre_pages import AuditFormatError


_SPACE = " \t\n\r\f"
_HEX = "0123456789abcdefABCDEF"
_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")
_VALUES = {
    "display": frozenset((
        "none", "block", "inline", "inline-block", "flex", "inline-flex", "grid", "inline-grid",
        "table", "inline-table", "table-row-group", "table-header-group", "table-footer-group",
        "table-row", "table-cell", "table-column-group", "table-column", "table-caption",
        "list-item", "contents", "flow-root", "initial", "inherit", "unset",
    )),
    "visibility": frozenset(("visible", "hidden", "collapse", "initial", "inherit", "unset")),
}


def _error(style: str, reason: str) -> AuditFormatError:
    return AuditFormatError(f"cannot safely resolve inline CSS ({reason}): {style[:160]!r}")


def _escape(style: str, position: int) -> tuple[str, int]:
    position += 1
    if position == len(style) or style[position] in "\n\r\f":
        raise _error(style, "invalid escape")
    end = position
    while end < min(position + 6, len(style)) and style[end] in _HEX:
        end += 1
    if end > position:
        codepoint = int(style[position:end], 16)
        value = chr(codepoint) if 0 < codepoint <= 0x10FFFF and not 0xD800 <= codepoint <= 0xDFFF else "\ufffd"
        if end < len(style) and style[end] in _SPACE:
            end += 2 if style[end:end + 2] == "\r\n" else 1
        return value, end
    return style[position], position + 1


def _name_character(char: str) -> bool:
    return char.isascii() and (char.isalnum() or char in "-_") or ord(char) >= 128


def _tokens(style: str) -> list[tuple[str, str]]:
    tokens = []
    position = 0
    while position < len(style):
        char = style[position]
        if char in _SPACE:
            position += 1
        elif char == "\0":
            raise _error(style, "NUL character")
        elif style.startswith("/*", position):
            end = style.find("*/", position + 2)
            if end < 0:
                raise _error(style, "unterminated comment")
            position = end + 2
        elif char in "\"'":
            quote = char
            position += 1
            value = []
            while position < len(style) and style[position] != quote:
                if style[position] in "\n\r\f":
                    raise _error(style, "newline in string")
                if style[position] == "\\":
                    if style[position + 1:position + 2] in {"\n", "\r", "\f"}:
                        position += 3 if style[position + 1:position + 3] == "\r\n" else 2
                        continue
                    escaped, position = _escape(style, position)
                    value.append(escaped)
                else:
                    value.append(style[position])
                    position += 1
            if position == len(style):
                raise _error(style, "unterminated string")
            tokens.append(("string", "".join(value)))
            position += 1
        elif char == "\\" or _name_character(char) and not char.isdecimal():
            value = []
            while position < len(style):
                if style[position] == "\\":
                    escaped, position = _escape(style, position)
                    value.append(escaped)
                elif _name_character(style[position]):
                    value.append(style[position])
                    position += 1
                else:
                    break
            tokens.append(("ident", "".join(value).translate(_LOWER)))
        else:
            tokens.append((char, char))
            position += 1
    return tokens


def inline_visibility(style: str) -> dict[str, str]:
    declarations: list[list[tuple[str, str]]] = [[]]
    brackets: list[str] = []
    for token in _tokens(style):
        kind = token[0]
        if kind in {"(", "[", "{"}:
            brackets.append({"(": ")", "[": "]", "{": "}"}[kind])
        elif kind in {")", "]", "}"}:
            if not brackets or brackets.pop() != kind:
                raise _error(style, "unmatched block delimiter")
        if kind == ";" and not brackets:
            declarations.append([])
        else:
            declarations[-1].append(token)
    if brackets:
        raise _error(style, "unterminated block")

    resolved: dict[str, tuple[bool, str]] = {}
    for declaration in declarations:
        if not declaration:
            continue
        if len(declaration) < 2 or declaration[0][0] != "ident" or declaration[1][0] != ":":
            raise _error(style, "unsupported declaration")
        name, value = declaration[0][1], declaration[2:]
        if name == "all":
            raise _error(style, "all requires the full cascade")
        if name not in _VALUES:
            continue
        important = value[-2:] == [("!", "!"), ("ident", "important")]
        if important:
            value = value[:-2]
        if len(value) != 1 or value[0][0] != "ident" or value[0][1] not in _VALUES[name]:
            raise _error(style, f"unsupported {name} value")
        if important or not resolved.get(name, (False, ""))[0]:
            resolved[name] = (important, value[0][1])
    return {name: value for name, (_, value) in resolved.items()}


def presentation_visibility(attributes: dict[str, str | None]) -> dict[str, str]:
    resolved = {}
    for name, allowed in _VALUES.items():
        if name not in attributes:
            continue
        value = attributes[name] or ""
        tokens = _tokens(value)
        if len(tokens) != 1 or tokens[0][0] != "ident" or tokens[0][1] not in allowed:
            raise _error(f"{name}={value}", "unsupported SVG presentation value")
        resolved[name] = tokens[0][1]
    return resolved

from pathlib import Path
import io
import tokenize

src = Path("/mnt/data/Pasted text(20261126-133617).txt")
text = src.read_text(encoding="utf-8")

# Blank Python comment tokens while preserving line breaks and source layout.
lines = text.splitlines(keepends=True)
offsets = []
pos = 0
for line in lines:
    offsets.append(pos)
    pos += len(line)

chars = list(text)
for tok in tokenize.generate_tokens(io.StringIO(text).readline):
    if tok.type == tokenize.COMMENT:
        start_line, start_col = tok.start
        end_line, end_col = tok.end
        start = offsets[start_line - 1] + start_col
        end = offsets[end_line - 1] + end_col
        for i in range(start, end):
            if chars[i] not in "\r\n":
                chars[i] = " "

cleaned = "".join(chars)

# Remove trailing whitespace left where full-line comments were removed.
cleaned_lines = [line.rstrip() + ("\n" if line.endswith("\n") else "") for line in cleaned.splitlines(keepends=True)]
# Collapse runs of blank lines to at most one blank line.
out_lines = []
blank_run = 0
for line in cleaned_lines:
    if not line.strip():
        blank_run += 1
        if blank_run <= 1:
            out_lines.append("\n" if line.endswith("\n") else "")
    else:
        blank_run = 0
        out_lines.append(line)

out = Path("/mnt/data/cleaned_script.py")
out.write_text("".join(out_lines), encoding="utf-8")
print(f"Created {out.name}")

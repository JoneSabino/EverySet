from __future__ import annotations

import base64
import hashlib
import re
from collections import Counter

from .models import RawBlock

_PHONE_RE = re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_ROLE_KEYWORDS = re.compile(
    r"\b(stand.?in|background|photo.?double|featured|special.?ability|audience|BG|PD|SI|SpA)\b",
    re.IGNORECASE,
)


def compute_fingerprint(blocks: list[RawBlock]) -> str:
    block_count = len(blocks)
    phone_blocks = sum(1 for b in blocks if _PHONE_RE.search(b.text))
    header_candidates = sum(
        1 for b in blocks if _ROLE_KEYWORDS.search(b.text) and not _PHONE_RE.search(b.text)
    )

    # Font size histogram: top 3 sizes
    sizes: list[float] = []
    for b in blocks:
        if b.font_size:
            sizes.append(round(b.font_size, 0))
    size_hist = Counter(sizes).most_common(3)
    size_key = "_".join(f"{s:.0f}x{c}" for s, c in sorted(size_hist))

    payload = f"{block_count}:{phone_blocks}:{header_candidates}:{size_key}"
    digest = hashlib.sha256(payload.encode()).digest()[:9]
    return base64.b32encode(digest).decode().rstrip("=")[:12]

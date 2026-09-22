from __future__ import annotations


def parse_page_spec(spec: str, page_count: int) -> list[int]:
    """Parse a 1-based page specification into sorted unique 0-based indexes.

    Supported forms:
        "4,11-60,120-150"
        "1, 3, 5-7"
        "4-60/7"       -> 4, 11, 18, ...
        "4-100/4"      -> 4, 8, 12, ...

    A stepped range always starts from the range's first page. This makes it
    useful for layouts that repeat every N pages with an arbitrary offset.
    """
    if page_count <= 0:
        raise ValueError("page_count must be positive")

    text = spec.strip()
    if not text:
        raise ValueError("ページ指定を入力してください")

    pages: set[int] = set()
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("空のページ指定があります")

        step = 1
        if "/" in part:
            if part.count("/") != 1:
                raise ValueError(f"不正な間隔指定です: {part}")
            base, step_text = (item.strip() for item in part.split("/", 1))
            if not step_text.isdigit() or int(step_text) < 1:
                raise ValueError(f"間隔は1以上の整数で指定してください: {part}")
            step = int(step_text)
            part = base
            if "-" not in part:
                raise ValueError(
                    f"間隔指定は範囲と組み合わせてください（例: 4-60/7）: {raw_part.strip()}"
                )

        if "-" in part:
            if part.count("-") != 1:
                raise ValueError(f"不正なページ範囲です: {part}")
            start_text, end_text = (item.strip() for item in part.split("-", 1))
            if not start_text.isdigit() or not end_text.isdigit():
                raise ValueError(f"不正なページ範囲です: {part}")
            start = int(start_text)
            end = int(end_text)
            if start > end:
                raise ValueError(f"範囲の開始頁が終了頁より後です: {part}")
            numbers = range(start, end + 1, step)
        else:
            if not part.isdigit():
                raise ValueError(f"不正なページ番号です: {part}")
            numbers = (int(part),)

        for number in numbers:
            if number < 1 or number > page_count:
                raise ValueError(
                    f"ページ番号が範囲外です: {number}（1〜{page_count}）"
                )
            pages.add(number - 1)

    return sorted(pages)

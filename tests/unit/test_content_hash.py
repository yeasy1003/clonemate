from clonemate import content_hash


def test_hash_is_sha256_prefix() -> None:
    h = content_hash.compute("hello world")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_hash_stable_across_calls() -> None:
    a = content_hash.compute("张三 (10:01): 你好")
    b = content_hash.compute("张三 (10:01): 你好")
    assert a == b


def test_hash_normalises_trailing_whitespace() -> None:
    """Trailing whitespace per line is stripped before hashing."""
    a = content_hash.compute("张三 (10:01): 你好\n李四 (10:02): 嗯")
    b = content_hash.compute("张三 (10:01): 你好   \n李四 (10:02): 嗯\t")
    assert a == b


def test_hash_distinguishes_different_content() -> None:
    a = content_hash.compute("hello")
    b = content_hash.compute("world")
    assert a != b

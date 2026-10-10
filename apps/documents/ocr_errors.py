"""The two ways a page read ends without pages, shared by every reader."""


class PageRefused(RuntimeError):
    """A page nobody can read: the student is asked to rescan, and nothing is guessed from it.

    `reason` is the reader's name for it -- low_resolution, too_many_pages, page_too_large,
    unreadable, text_too_small or cut_off -- and `page` is 1-based. (`not_a_transcript` is
    transcript_pages' own refusal, decided across the upload's pages, never raised here.)
    """

    def __init__(self, reason: str, page: int) -> None:
        super().__init__(f"page {page}: {reason}")
        self.reason = reason
        self.page = page


class OcrUnavailable(RuntimeError):
    """The engine did not answer -- a crash, a timeout, a missing interpreter. Never a refusal."""

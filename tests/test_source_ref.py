from renta.models import SourceRef


def _ref(file="samples/2025/Fidelity_2025_Tax_Statement.pdf", page=3, row=6, section="dividends"):
    return SourceRef(file=file, page=page, row=row, section=section)


def test_short():
    ref = _ref(page=3, row=6)
    assert ref.short == "pág 3 · fila 7"


def test_short_fila_one_indexed():
    ref = _ref(page=1, row=0)
    assert ref.short == "pág 1 · fila 1"


def test_file_label_strips_path():
    ref = _ref(file="samples/2025/Fidelity_2025_Tax_Statement.pdf")
    assert ref.file_label == "Fidelity_2025_Tax_Statement.pdf"


def test_file_label_no_path():
    ref = _ref(file="archivo.pdf")
    assert ref.file_label == "archivo.pdf"


def test_str_unchanged():
    ref = _ref(file="samples/2025/Fidelity.pdf", page=2, row=4, section="dividends")
    assert str(ref) == "samples/2025/Fidelity.pdf · pág 2, fila 5 (dividends)"

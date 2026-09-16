from pdf_textlayer_probe import same_text


def test_pdf_roundtrip_must_not_accept_missing_indic_clusters():
    assert same_text("पत्र लिखना", "पत्र\nलिखना")
    assert not same_text("पत्र लिखना", "प लखना")
    assert not same_text("त्र", "\x00")


def test_pdf_roundtrip_must_not_fold_radicals_into_source_ideographs():
    assert same_text("页面 门 贝", "页面\n门 贝")
    assert not same_text("页面 门 贝", "⻚⾯⻔⻉")
    assert not same_text("联系人", "联系⼈")
    assert not same_text("联系人", "人系联")

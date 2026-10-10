"""The extraction evaluation corpus: six CVs whose answer key is exact.

Why synthetic. The published sample CVs this was first measured against
(UPenn Career Services) redact every date to `20XX` and some titles to
`TITLE`, so they measure structure and stability well and accuracy not at all.
These six are written here, which means the value on the page and the value in
the key come from the same dict and cannot drift apart.

Why no PDFs in git. The documents are built by WeasyPrint at test time from the
HTML below -- the repo already renders PDFs, so this adds no dependency and no
binaries. The two Harvard College résumé samples that were also measured are
deliberately absent: they are third-party documents whose redistribution terms
have not been checked, and a test must not fetch over the network to find out.
The floors in test_extraction_accuracy.py are therefore stated over these six.

One document per format family, because the formats are the thing being
claimed: a CV can print a date in a finite number of ways and the claim is that
we read all of them. Adding a family means adding a document here, not
loosening a threshold.

Measured 2026-08-31, two runs over eight documents: entries 59/60, dates
118/118, names 16/16, languages 16/16. See
docs/superpowers/research/2026-08-31-cv-extraction-baseline.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from weasyprint import HTML

from apps.documents.dates import Convention

_CSS = "<style>body{font-family:sans-serif;font-size:11pt} td{padding-right:8mm}</style>"


@dataclass(frozen=True)
class CorpusDocument:
    """One CV, its answer key, and the date forms it prints.

    ``education``/``experience`` rows are (label, organisation, start, end).
    Dates are keyed at the precision the page states: "2023-06" means the
    document named June 2023 and no day, so any date in that month is a correct
    reading. Asserting the 30th would score a convention rather than a reading.
    """

    html: str
    full_name: str
    education: tuple[tuple[str, str, str | None, str | None], ...] = ()
    experience: tuple[tuple[str, str, str | None, str | None], ...] = ()
    languages: tuple[str, ...] = ()
    #: (written on the page, "start" or "end", expected ISO date or None).
    #: Scored without a model call, so the format table cannot silently lose a
    #: form this corpus depends on.
    dates: tuple[tuple[str, str, str | None], ...] = ()
    convention: Convention = Convention.DAY_FIRST

    def pdf(self) -> bytes:
        return HTML(string=_CSS + self.html).write_pdf()


CORPUS: dict[str, CorpusDocument] = {
    "english-months": CorpusDocument(
        html="""
<h1>Leyla Mammadova</h1>
<p>Baku, Azerbaijan | leyla.mammadova@example.az | +994 50 123 45 67</p>
<h2>Education</h2>
<p><b>MSc in Data Science</b>, ADA University, Baku, Azerbaijan<br>
September 2022 - June 2024<br>Grade: 92/100</p>
<p><b>BSc in Mathematics</b>, Baku State University, Baku, Azerbaijan<br>
September 2018 - June 2022</p>
<h2>Experience</h2>
<p><b>Data Analyst</b>, PashaBank, Baku, Azerbaijan<br>July 2024 - Present</p>
<ul><li>Built the retail churn model.</li></ul>
<p><b>Intern</b>, Azercell, Baku, Azerbaijan<br>June 2021 - August 2021</p>
<ul><li>Wrote reporting scripts.</li></ul>
<h2>Languages</h2><p>Azerbaijani (native), English (C1), Turkish (B2)</p>
""",
        full_name="Leyla Mammadova",
        education=(
            ("MSc in Data Science", "ADA University", "2022-09", "2024-06"),
            ("BSc in Mathematics", "Baku State University", "2018-09", "2022-06"),
        ),
        experience=(
            ("Data Analyst", "PashaBank", "2024-07", None),
            ("Intern", "Azercell", "2021-06", "2021-08"),
        ),
        languages=("Azerbaijani", "English", "Turkish"),
        dates=(
            ("September 2022", "start", "2022-09-01"),
            ("June 2024", "end", "2024-06-30"),
            ("July 2024", "start", "2024-07-01"),
            ("Present", "end", None),
        ),
        # the commonest shape: English month names, an open-ended range
    ),
    "german-tabular": CorpusDocument(
        html="""
<h1>Jonas Weber</h1>
<p>Musterstrasse 1, 10115 Berlin | jonas.weber@example.de</p>
<h2>Ausbildung</h2>
<table>
<tr><td>WS 2020/21 - SS 2023</td>
    <td><b>M.Sc. Maschinenbau</b>, Technische Universitaet Muenchen</td></tr>
<tr><td>10/2016 - 09/2020</td><td><b>B.Sc. Maschinenbau</b>, RWTH Aachen</td></tr>
</table>
<h2>Berufserfahrung</h2>
<table>
<tr><td>01.10.2023 - heute</td><td><b>Entwicklungsingenieur</b>, Siemens AG, Muenchen</td></tr>
</table>
""",
        full_name="Jonas Weber",
        education=(
            ("M.Sc. Maschinenbau", "Technische Universitaet Muenchen", "2020-10", "2023-09"),
            ("B.Sc. Maschinenbau", "RWTH Aachen", "2016-10", "2020-09"),
        ),
        experience=(("Entwicklungsingenieur", "Siemens AG", "2023-10-01", None),),
        dates=(
            ("WS 2020/21", "start", "2020-10-01"),
            ("SS 2023", "end", "2023-09-30"),
            ("10/2016", "start", "2016-10-01"),
            ("01.10.2023", "start", "2023-10-01"),
            ("heute", "end", None),
        ),
        # tabellarischer Lebenslauf: semesters, dotted numerics, no country named
    ),
    "us-seasons": CorpusDocument(
        html="""
<h1>Sarah Chen</h1>
<p>Philadelphia, PA | schen@example.edu</p>
<h2>Education</h2>
<p><b>Ph.D. in Chemistry</b>, University of Pennsylvania, Philadelphia, PA<br>
Fall 2019 - Spring 2025</p>
<p><b>B.S. in Chemistry</b>, University of Michigan, Ann Arbor, MI<br>
09/02/2015 - 05/15/2019</p>
<h2>Research Experience</h2>
<p><b>Graduate Research Assistant</b>, Penn Chemistry, Philadelphia, PA<br>
Fall 2019 - Present</p>
<ul><li>Synthesised gold nanoprisms.</li></ul>
<h2>Publications</h2>
<p>Chen, S., Patel, R. (2024). Raspberry-like metamolecules. <i>ACS Nano</i>.</p>
<h2>Conference Presentations</h2>
<p>Chen, S. (2023). Dark quadrupole modes. ACS Spring Meeting, poster.</p>
<h2>References</h2>
<p>Prof. Alan Reed, Department of Chemistry, University of Pennsylvania, areed@example.edu</p>
""",
        full_name="Sarah Chen",
        education=(
            ("Ph.D. in Chemistry", "University of Pennsylvania", "2019-09", "2025-05"),
            ("B.S. in Chemistry", "University of Michigan", "2015-09-02", "2019-05-15"),
        ),
        experience=(("Graduate Research Assistant", "Penn Chemistry", "2019-09", None),),
        dates=(
            ("Fall 2019", "start", "2019-09-01"),
            ("Spring 2025", "end", "2025-05-31"),
            ("09/02/2015", "start", "2015-09-02"),
            ("05/15/2019", "end", "2019-05-15"),
        ),
        convention=Convention.MONTH_FIRST,
        # US academic: seasons, month-first numerics, and no country anywhere
    ),
    "day-first-gap": CorpusDocument(
        html="""
<h1>Mehmet Yilmaz</h1>
<p>Istanbul, Turkiye | mehmet.yilmaz@example.com.tr</p>
<h2>Education</h2>
<p><b>Lisans, Endustri Muhendisligi</b>, Bogazici Universitesi, Istanbul, Turkiye<br>
15/09/2014 - 30/06/2018</p>
<h2>Experience</h2>
<p><b>Uretim Muhendisi</b>, Arcelik, Istanbul, Turkiye<br>01/07/2020 - 31/12/2023</p>
<ul><li>Hat verimliligini artirdi.</li></ul>
<h2>Military Service</h2>
<p>Turkish Armed Forces, 01/07/2018 - 30/06/2019</p>
""",
        full_name="Mehmet Yilmaz",
        education=(
            (
                "Lisans, Endustri Muhendisligi",
                "Bogazici Universitesi",
                "2014-09-15",
                "2018-06-30",
            ),
        ),
        experience=(("Uretim Muhendisi", "Arcelik", "2020-07-01", "2023-12-31"),),
        dates=(
            ("15/09/2014", "start", "2014-09-15"),
            ("30/06/2018", "end", "2018-06-30"),
            ("01/07/2020", "start", "2020-07-01"),
        ),
        # day-first numerics throughout, and a service gap between two roles
    ),
    "abbrev-thesis": CorpusDocument(
        html="""
<h1>Ana Silva</h1>
<p>Lisbon, Portugal | ana.silva@example.pt</p>
<h2>Education</h2>
<p><b>MSc in Bioinformatics</b>, Universidade de Lisboa, Lisbon, Portugal<br>
Sept. 2021 - Jun. 2023<br>
Thesis: Graph neural networks for protein folding<br>
Rank: 3rd of 120</p>
<h2>Experience</h2>
<p><b>Research Assistant</b>, Instituto Gulbenkian, Oeiras, Portugal<br>
Oct 2023 - Dec 2024</p>
<ul><li>Maintained the sequencing pipeline.</li></ul>
""",
        full_name="Ana Silva",
        education=(("MSc in Bioinformatics", "Universidade de Lisboa", "2021-09", "2023-06"),),
        experience=(("Research Assistant", "Instituto Gulbenkian", "2023-10", "2024-12"),),
        dates=(
            ("Sept. 2021", "start", "2021-09-01"),
            ("Jun. 2023", "end", "2023-06-30"),
            ("Oct 2023", "start", "2023-10-01"),
            ("Dec 2024", "end", "2024-12-31"),
        ),
        # abbreviated months, a thesis under the degree, and a class rank
    ),
    "year-only": CorpusDocument(
        html="""
<h1>Nurlan Aliyev</h1>
<p>nurlan.aliyev@example.az</p>
<h2>Education</h2>
<p><b>PhD in Physics</b>, Khazar University, Baku, Azerbaijan, 2019 - 2023</p>
<p><b>MSc in Physics</b>, Khazar University, Baku, Azerbaijan, 2017 - 2019</p>
<h2>Experience</h2>
<p><b>Lecturer</b>, Khazar University, Baku, Azerbaijan, 2023 - 2025</p>
<ul><li>Taught undergraduate mechanics.</li></ul>
""",
        full_name="Nurlan Aliyev",
        education=(
            ("PhD in Physics", "Khazar University", "2019", "2023"),
            ("MSc in Physics", "Khazar University", "2017", "2019"),
        ),
        experience=(("Lecturer", "Khazar University", "2023", "2025"),),
        dates=(
            ("2019", "start", "2019-01-01"),
            ("2023", "end", "2023-12-31"),
        ),
        # the coarsest shape a real CV uses: a year and nothing else
    ),
}

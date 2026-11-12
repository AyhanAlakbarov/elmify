# Government-only domain zones: registry policy citations

Date: 2026-10-03. Serves: `apps/research/recognition.py` `GOVERNMENT_ZONES`. A zone is added only when the registry's or the government domain authority's own page shows the zone is restricted to government bodies.

## Scope

1. For each candidate zone: which page, owned by the registry or the government domain authority, says who may register?
2. Does that page state a restriction ("only", "reserved", "dedicated only") or only a description or recommendation?
3. Is the restriction enforced, either by required documents or by approval from a named authority?
4. For the six existing zones: do their current citation URLs still load?

Method. Candidate URLs came from an Exa `agent_run` (leads only) plus one Exa search per zone, with Brave `site:` searches for gov.uk, gov.kz, gov.ng and gouv.fr. Every quote below was copied from a scrapling `get` of the cited URL. The one exception is gov.et, which loaded only through scrapling `stealthy_fetch` because a plain fetch fails on its TLS chain. Tavily was not used. The coordinator stopped the run before every zone was finished, and every unfinished zone is marked UNVERIFIED.

Verdict key:
- **ADD**: the page states a restriction to government or public bodies, and it is enforced.
- **ADD (caveat)**: the same, but the eligible set is wider than "government bodies" (for example state companies, public trusts or professional chambers). The caller decides.
- **DO NOT ADD**: the page loaded but shows only a description or recommendation, or no exclusivity.
- **UNVERIFIED**: no owner page could be loaded and quoted.

## Table

| zone | policy URL | quote (verbatim) | enforced? | verdict |
|---|---|---|---|---|
| gov.az | https://scis.gov.az/en/pages/view/dns-xidmeti | "GOV.AZ (Government.az) is a special domain zone reserved for the naming of Internet information resources of state bodies."[^1] | Yes. A written application to the Special State Protection Service plus a registration form, and a decision within 5 working days.[^2] | **ADD** |
| gov.kz | https://nic.kz/ru/domains/faq | "необходимо предоставить соответствующие документы, удостоверяющие принадлежность регистранта к ISP, некоммерческим, образовательным или правительственным организациям"[^3] | Yes. Documents are required, and gov.kz is registered only by АО НИТ.[^4] The eligibility sentence "GOV.KZ … для государственных органов" was quoted from the 2016 rules, which nic.kz marks as repealed.[^5] | **ADD (caveat)**: the current 2018 rules are on adilet.zan.kz, which returned an empty page |
| gov.ge | https://nic.ge/en/domains/what-is-a-domain-name | "can only be registered under the name of state entities, or local self-government units or organizations, legal entities under public law"[^6] | Yes. Registration is delegated to LEPL "Smart Logic" of the Ministry of Justice.[^7] Cultural, educational and scientific public-law bodies are excluded. | **ADD** |
| gov.uk | https://www.gov.uk/guidance/check-if-your-organisation-can-get-a-govuk-domain-name | "Only the following organisations can apply for a .gov.uk domain name"[^8] | Yes. Written permission from the CEO or CIO is required, and the Domains Team checks it.[^9] The list includes "partnership bodies" and bodies representing groups of public bodies. | **ADD** |
| gov.au | https://www.domainname.gov.au/policies/eligibility-and-allocation-policy | "The Registrant must be an organisation established by an Act of Parliament or government regulation as a government department or agency"[^10] | Yes. The Domain Provider assesses each application.[^11] | **ADD** |
| gov.sa | https://nic.sa/en/help/regulation/ | "Dedicated only for governmental entities in the Kingdom of Saudi Arabia including ministries, authorities, and general agencies."[^12] | Yes. Registration happens only through the Digital Government Authority.[^13] | **ADD** |
| gov.qa | https://www.cra.gov.qa/en/Regulatory-Framework/Domain-Management/Registrants | "are dedicated only for the governmental entities, education institutions, schools and official organizations located in the State of Qatar"[^14] | Yes. CRA registers these zones directly.[^15] The exclusivity sentence groups gov.qa with edu.qa, sch.qa, org.qa and mil.qa. The per-zone line reads "For Qatar governmental organizations". | **ADD** |
| gov.ae | (TDRA .ae Domain Name Policy is a PDF, `.ashx`) | not quoted | Search text says "The Registrant must be a Government Entity in the UAE" and that a ministerial letter is required. Not fetched. | **UNVERIFIED** |
| gov.bn | https://www.bnnic.bn/faqs/item/2-introduction-to-registration-procedure | not quoted | Timed out on a plain fetch and in a browser | **UNVERIFIED** |
| gov.sg | https://www.sgnic.sg/domain-registration/sg-categories-rules | "Only government bodies or members of the Singapore Government are eligible to apply under this category."[^16] | Stated as a mandatory eligibility rule. The mechanism (an SGNIC-appointed registrar) appears only in a third-party copy of the RPPG and is not cited. | **ADD** |
| gov.kw | https://www.kw/en/support/faqs/ | ".gov.kw - Which represents a \"Government\" Entity."[^17] | Not shown. The page says accredited registrars decide eligibility. | **DO NOT ADD** (description only) |
| gov.bh | https://www.nea.gov.bh/HTML/WDS/2.3%20Website%20Domain%20Naming%20Standards.html | "domain name registration for Government and semi-Government organization is handled by the Information and eGovernment Authority (IGA)"[^18] | IGA handles registration, but "semi-Government" bodies are included and the registry's own rules (register.bh) do not list gov.bh | **DO NOT ADD** |
| gov.ru | http://government.ru/docs/all/166131/ | "Регистрация доменных имен gov.ru, kremlin.ru, government.ru, правительство.рф и президент.рф осуществляется в соответствии с настоящими Правилами и соглашением"[^19] | The FSO controls gov.ru by agreement, but no published rule says who may get a subdomain | **DO NOT ADD** (no eligibility rule) |
| gov.cn | https://www.cac.gov.cn/2012-05/28/c_126540129.htm | "申请者应为行政机关法人或者法律、行政法规规定的行使行政职能的事业单位"[^20] | Yes. A sealed application plus proof of government status.[^21] This is the 2012 CNNIC rules text, hosted by CAC. | **ADD** |
| gov.vn | https://archive.vnnic.vn/tenmien/chinhsach/quy-trinh-dang-ky-ten-mien-duoi-govvn | "Cơ quan nhà nước ở trung ương và địa phương được quy định tại các Luật"[^22] | Yes. VNNIC reviews and decides each file in advance.[^23] The cited page uses Circular 24/2015, which Circular 48/2025 replaced from 10 Feb 2026.[^24] | **ADD** |
| gov.rs | https://www.uzzpro.gov.rs/latinica/procedure.html | "Procedura za registraciju domena za državne organe"[^25] | Yes. An official signed letter plus an Official Gazette act proving entitlement.[^26] | **ADD** |
| gov.uz | https://cctld.uz/info/polru/?lang=eng | not quoted (the § 8 "Государственное доменное имя" body is collapsed and JS-loaded) | unknown | **UNVERIFIED** |
| gov.am | (ISOC Armenia policy is a PDF; it lists com/co/org/net/commune.am only) | not quoted | unknown | **UNVERIFIED** |
| gov.br | https://www.gov.br/pt-br/servicos/registrar-endereco-de-sitio-eletronico-gov.br | "sítios governamentais dos órgãos e entidades da administração pública federal direta, autárquica e fundacional do Poder Executivo Federal"[^27] | Yes. Prior authorisation by the Secretaria de Governo Digital.[^28] Covers federal bodies only. State sub-zones (e.g. sp.gov.br) were not checked. Federal autarquias include federal universities. | **ADD (caveat)** |
| gob.mx | https://www.dominios.mx/dominios-gob-mx/ | "cualquier otra organización no incluida en el listado anterior no podrá ser registrada bajo un dominio .gob.mx"[^29] | Yes. Official appointment and ID documents, validated by Registry .MX.[^30] The list includes state and parastatal companies, embassies and public trusts. | **ADD (caveat)** |
| gov.za | http://dnsadmin.gov.za/faq.htm | "Any South African government department that wishes to establish an Internet sub-domain within GOV.ZA domain"[^31] | Yes. A signed form from a CIO/Director-level official is required, and SITA processes it.[^32] HTTP only. | **ADD** |
| gov.ng | https://nitda.gov.ng/gov-ng-domain-registration/ | "is ONLY permitted for the Federal Government, State Government, Federal Ministries, Departments, Parastatals and Institutions"[^33] | Yes. NITDA verifies the authorisation letter.[^34] Parastatals are included. | **ADD (caveat)** |
| go.ke | https://kenic.or.ke/faqs/ | not quoted | Timed out on a plain fetch and in a browser. Search text says an ICTA/GITS authority letter is required. | **UNVERIFIED** |
| gov.eg | https://domain.eg/registration-requirements | "للجهات الحكومية أو الشركة الحكومية: خطاب من الجهة الحكومية مختوم بختم النسر"[^35] | Yes. A letter from a government body bearing the eagle seal. Government companies are also eligible. There is no explicit "only" sentence. | **ADD (caveat)** |
| gov.ma | https://www.registre.ma/language/en/domain-name/e-descriptive-extensions | not quoted | TLS error on a plain fetch, connection reset in a browser | **UNVERIFIED** |
| gov.gh | https://www.nic.gh/registrars.html | not quoted (the page only lists NITA as "Responsible for .gov.gh domains") | unknown | **UNVERIFIED** |
| gov.et | https://myportal.ethiotelecom.et/index.php/knowledgebase/10/Can-I-purchase-any-domain-extension.html | "should be subscribed by government bodies and institutions under the Domain Naming Guidelines"[^36] | "should" wording, in a hosting-portal knowledge-base article. The page loads only in a browser. | **DO NOT ADD** |
| gc.ca | https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=24227 | "Primary domain names for Government of Canada websites and Web applications are registered in the Canada.ca or .gc.ca sub-domain."[^37] | Approval is required for departments.[^38] The page says departments must use gc.ca, not that only they may. | **DO NOT ADD** (no exclusivity statement found) |
| gouv.fr | (AFNIC naming charter, PDF only) | not quoted | Search text reads "L’extension «.gouv.fr » ainsi que ses versions IDN sont réservées au gouvernement français", with SIG validation required. PDF not fetched. | **UNVERIFIED** (strong lead) |
| gov.it | https://www.nic.it/it/domini-gov-it | "può essere effettuata solo da quelle Pubbliche Amministrazioni presenti nel suddetto elenco"[^39] | Yes. A validation phase by the Registro .it, with an IPA listing required.[^40] | **ADD** |
| gov.pl | https://www.dns.pl/informacje_o_rejestracji_domen_gov_pl | "Nazwy w domenie .gov.pl mogą zarejestrować wyłącznie uprawnione podmioty"[^41] | Yes. Registration happens only directly at NASK.[^42] Professional self-government chambers are also eligible. | **ADD (caveat)** |
| gv.at | (ref.gv.at policy PDF) | not quoted | unknown | **UNVERIFIED** |
| admin.ch | (bk.admin.ch, fedlex) | not quoted | unknown | **UNVERIFIED** |
| gov.ie | (gov.ie pages) | not quoted | unknown | **UNVERIFIED** |

### The six existing zones

| zone | URL checked | result |
|---|---|---|
| gov | https://get.gov/domains/eligibility/ | Loads. The page says "Only verified U.S. government organizations can register and operate a .gov domain".[^43] |
| gov.tr, go.jp, go.kr, europa.eu, auswaertiges-amt.de | n/a | **UNVERIFIED**. `apps/research/recognition.py` does not exist in either `/home/orkhan/Desktop/elmify` or `/home/orkhan/Desktop/elmify-design`, so their current citation URLs could not be read. |

## Notes

- Several zones admit more than "government bodies": gob.mx (state companies, public trusts), gov.eg (government companies), gov.ng (parastatals), gov.pl (professional chambers), gov.uk (partnership bodies), gov.br (federal autarquias and foundations, which include federal universities), and gov.qa (one sentence covers five zones). The caller should decide whether "state-controlled" is close enough.
- Some cited pages are not the current rule text. For gov.kz, the restriction sentence comes from rules that nic.kz itself marks "Утратил силу" (repealed). For gov.vn, the cited archive page refers to a superseded circular. For gov.cn, the text is the 2012 rules.

## Sources

[^1]: https://scis.gov.az/en/pages/view/dns-xidmeti "GOV.AZ (Government.az) is a special domain zone reserved for the naming of Internet information resources of state bodies."
[^2]: https://scis.gov.az/en/pages/view/dns-xidmeti "Administration of the domain is carried out only if both of the above-mentioned applications are submitted."
[^3]: https://nic.kz/ru/domains/faq "необходимо предоставить соответствующие документы, удостоверяющие принадлежность регистранта к ISP, некоммерческим, образовательным или правительственным организациям"
[^4]: https://nic.kz/ru/domains/faq "Регистрацию в зонах *.gov.kz, *.мем.қаз производит АО НИТ"
[^5]: https://www.nic.kz/ru/doc/prikaz28-2016-118 "GOV.KZ - предназначенные для регистрации доменных имен третьего уровня для государственных органов Республики Казахстан"
[^6]: https://nic.ge/en/domains/what-is-a-domain-name "can only be registered under the name of state entities, or local self-government units or organizations, legal entities under public law"
[^7]: https://nic.ge/en/domains/what-is-a-domain-name "right to register such Domain Names is delegated to the LEPL"
[^8]: https://www.gov.uk/guidance/check-if-your-organisation-can-get-a-govuk-domain-name "Only the following organisations can apply for a .gov.uk domain name"
[^9]: https://www.gov.uk/guidance/get-permission-to-apply-for-a-govuk-domain-name "You must get written permission from your Chief Executive or equivalent."
[^10]: https://www.domainname.gov.au/policies/eligibility-and-allocation-policy "The Registrant must be an organisation established by an Act of Parliament or government regulation as a government department or agency"
[^11]: https://www.domainname.gov.au/policies/eligibility-and-allocation-policy "The Domain Provider for your jurisdiction will assess domain name applications against the following policies"
[^12]: https://nic.sa/en/help/regulation/ "Dedicated only for governmental entities in the Kingdom of Saudi Arabia including ministries, authorities, and general agencies."
[^13]: https://nic.sa/en/ "Registering new domains is done only from the Digital Government Authority."
[^14]: https://www.cra.gov.qa/en/Regulatory-Framework/Domain-Management/Registrants "are dedicated only for the governmental entities, education institutions, schools and official organizations located in the State of Qatar"
[^15]: https://www.cra.gov.qa/en/Regulatory-Framework/Domain-Management/Registrants "will be registered by CRA directly"
[^16]: https://www.sgnic.sg/domain-registration/sg-categories-rules "Only government bodies or members of the Singapore Government are eligible to apply under this category."
[^17]: https://www.kw/en/support/faqs/ ".gov.kw - Which represents a \"Government\" Entity."
[^18]: https://www.nea.gov.bh/HTML/WDS/2.3%20Website%20Domain%20Naming%20Standards.html "domain name registration for Government and semi-Government organization is handled by the Information and eGovernment Authority (IGA)"
[^19]: http://government.ru/docs/all/166131/ "Регистрация доменных имен gov.ru, kremlin.ru, government.ru, правительство.рф и президент.рф осуществляется в соответствии с настоящими Правилами и соглашением"
[^20]: https://www.cac.gov.cn/2012-05/28/c_126540129.htm "申请者应为行政机关法人或者法律、行政法规规定的行使行政职能的事业单位"
[^21]: https://www.cac.gov.cn/2012-05/28/c_126540129.htm "证明申请单位为政府机构的相关资料"
[^22]: https://archive.vnnic.vn/tenmien/chinhsach/quy-trinh-dang-ky-ten-mien-duoi-govvn "Cơ quan nhà nước ở trung ương và địa phương được quy định tại các Luật"
[^23]: https://archive.vnnic.vn/tenmien/chinhsach/quy-trinh-dang-ky-ten-mien-duoi-govvn "có trách nhiệm chuyển hồ sơ cho VNNIC để xem xét quyết định"
[^24]: https://vnnic.vn/vi/van-ban-so-lieu/thong-tu-so-482025tt-bkhcn/phan-loai-quy-dinh-doi-voi-tung-nhom-doi-tuong "Thông tư có hiệu lực kể từ ngày 10 tháng 02 năm 2026."
[^25]: https://www.uzzpro.gov.rs/latinica/procedure.html "Procedura za registraciju domena za državne organe"
[^26]: https://www.uzzpro.gov.rs/latinica/procedure.html "kojim se dokazuje da registrant ima pravo na domen"
[^27]: https://www.gov.br/pt-br/servicos/registrar-endereco-de-sitio-eletronico-gov.br "sítios governamentais dos órgãos e entidades da administração pública federal direta, autárquica e fundacional do Poder Executivo Federal"
[^28]: https://www.gov.br/pt-br/servicos/registrar-endereco-de-sitio-eletronico-gov.br "A resposta sobre a autorização de publicação será dada ao órgão via sistema."
[^29]: https://www.dominios.mx/dominios-gob-mx/ "cualquier otra organización no incluida en el listado anterior no podrá ser registrada bajo un dominio .gob.mx"
[^30]: https://www.dominios.mx/dominios-gob-mx/ "Registry .MX recibe, valida y activa o rechaza la solicitud de dominio .gob.mx"
[^31]: http://dnsadmin.gov.za/faq.htm "Any South African government department that wishes to establish an Internet sub-domain within GOV.ZA domain"
[^32]: http://dnsadmin.gov.za/faq.htm "person must be of a level/rank equivalent to CIO or Director"
[^33]: https://nitda.gov.ng/gov-ng-domain-registration/ "is ONLY permitted for the Federal Government, State Government, Federal Ministries, Departments, Parastatals and Institutions"
[^34]: https://nitda.gov.ng/gov-ng-domain-registration/ "to verify the authenticity of the authorization letter"
[^35]: https://domain.eg/registration-requirements "للجهات الحكومية أو الشركة الحكومية: خطاب من الجهة الحكومية مختوم بختم النسر"
[^36]: https://myportal.ethiotelecom.et/index.php/knowledgebase/10/Can-I-purchase-any-domain-extension.html "should be subscribed by government bodies and institutions under the Domain Naming Guidelines"
[^37]: https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=24227 "Primary domain names for Government of Canada websites and Web applications are registered in the Canada.ca or .gc.ca sub-domain."
[^38]: https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=24227 "Ensuring that domain names are approved for use, in consultation with the Privy Council Office."
[^39]: https://www.nic.it/it/domini-gov-it "può essere effettuata solo da quelle Pubbliche Amministrazioni presenti nel suddetto elenco"
[^40]: https://www.nic.it/it/domini-gov-it "ha lo scopo di verificare che la Pubblica Amministrazione possegga i requisiti"
[^41]: https://www.dns.pl/informacje_o_rejestracji_domen_gov_pl "Nazwy w domenie .gov.pl mogą zarejestrować wyłącznie uprawnione podmioty"
[^42]: https://www.dns.pl/informacje_o_rejestracji_domen_gov_pl "Rejestracja nazw w domenie .gov.pl odbywa się wyłącznie bezpośrednio w NASK."
[^43]: https://get.gov/domains/eligibility/ "Only verified U.S. government organizations can register and operate a .gov domain"

## Open questions

- **gouv.fr**: the AFNIC charter (PDF, July 2026 version) carries the restriction and the SIG-validation requirement. It needs a PDF-capable fetch to cite.
- **gov.ae**: the TDRA Domain Name Policy §15 (PDF) needs the same.
- **gv.at, admin.ch, gov.ie, gov.uz, gov.am, gov.bn, go.ke, gov.ma, gov.gh**: not finished. go.ke, gov.bn and gov.ma timed out or reset from this host. Retry them through Firecrawl or scrape.do.
- **gov.kz**: the current 2018 rules (adilet.zan.kz V1800016654) render empty without JS.
- **gov.br state sub-zones** and **gov.sg's enforcement mechanism** were not verified.
- **Existing five** (gov.tr, go.jp, go.kr, europa.eu, auswaertiges-amt.de): `recognition.py` was not found, so their citation URLs are unknown. Point the next run at the file or branch that holds it.

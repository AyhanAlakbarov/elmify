/** The server's FillPacket, as JSON. Mirrors apps/portals/packets.py. */
export interface PacketField {
  /** Where to type. Verified against the live page before use -- see verify.ts. */
  selector: string;
  /** One of FILL_METHODS. Never setFiles: documents are not field-map entries. */
  method: string;
  value: string;
  /** "category.key", e.g. "personal.given_name". Added by task 2; the
   *  verification check cannot judge a control without knowing what it is for. */
  profile_field: string;
  /** Typed back from this student's own earlier answer in this box (decision
   *  B): the label check is skipped and the mark says "From your earlier answer". */
  from_answer?: boolean;
  /** Filled from a value a document read proved: "passport" | "diploma" |
   *  "certificate"; the mark says "From your passport". */
  source_kind?: string;
}

export interface PacketDocument {
  filename: string;
  download_path: string;
  /** Exactly one of draft_id, upload_id and prepared_id is set (packets.py::PacketDocument). */
  draft_id: string | null;
  upload_id?: string | null;
  prepared_id?: string | null;
  /** The learned upload box (plan 5); absent or null keeps the name match. */
  selector?: string | null;
  /** FILE_FIELDS document: CV, TRANSCRIPT, DIPLOMA, ..., EVERY_DOCUMENT. */
  kind?: string;
  content_type?: string;
  /** Why the file could not be prepared (signed, too_large, ...), or "". */
  note?: string;
}

/** A note with no packet document of its own: an upload's, or the refused
 *  whole-application bundle's (kind "EVERY_DOCUMENT"). Codes only; the panel
 *  says each in the student's language. */
export interface PacketNote {
  kind: string;
  note: string;
}

/** A held document code could not place; the student picks the box. */
export interface PacketChoice {
  filename: string;
  download_path: string;
  kind: string;
  draft_id?: string | null;
  upload_id?: string | null;
  prepared_id?: string | null;
  selectors: string[];
}

/** A doubtful value a document read left (spec 2026-10-12 §7.2). Typed only
 *  after the student's tap confirms it on the server. */
export interface PacketOffer {
  fact_id: string;
  value: string;
  method: string;
  source_kind: "passport" | "diploma" | "certificate";
}

/** A control the map is not sure of, or the student holds no fact for. Typed
 *  into only after the student taps its offer. */
export interface PacketHint {
  selector: string;
  profile_field: string;
  reason: "unsure" | "no_fact";
  offer?: PacketOffer | null;
  upload_kind?: string;
  expired_on?: string;
}

export interface FillPacket {
  application_id: string;
  portal_form_id: string;
  field_map_version: number;
  form_url: string;
  entries: PacketField[];
  documents: PacketDocument[];
  hints?: PacketHint[];
  choices?: PacketChoice[];
  issued_at: string;
  expires_at: string;
  min_extension_version: string;
  /** From PortalForm.confirmation_markers via the packet. The server does not
   *  send this yet -- the column does not exist -- so it is absent on every
   *  real packet today; see content/page_signals.ts::detectConfirmation. */
  confirmation_markers: string[] | null;
  /** contact.email without our tag; "" (or absent, from an older server) when
   *  the address carries none. Typed instead when the portal refuses the tag. */
  plain_email?: string;
  /** Absent from an older server. */
  notes?: PacketNote[];
  /** Field class -> the one read-back rule the bench taught for this portal. */
  equivalences?: Record<string, string>;
}

/** How the extension knows a portal refused the tagged address. Mirrors
 *  apps/portals/ext_api.py::_REJECTION_EVIDENCE; a test pins it. Every kind
 *  is evidence about this student's account only, never the portal's shared
 *  status. */
export type RejectionEvidence = "form" | "page" | "after_submit" | "student";

export type FieldStateKind =
  | "filled" // we typed it and read back the same value
  | "already" // the page already held exactly our value
  | "elsewhere" // the control is not on this page (multi-page form)
  | "your_turn" // refused: hidden, disabled, mislabelled, no option, no fact
  | "changed_by_you" // the student typed into it during this run (a trusted input event)
  | "portal_error" // the portal flagged the control after a submit/next
  | "mismatch"; // the page holds something else after our fill, or held another value before it ("held_other")
export interface FieldView {
  key: string; // profile_field, e.g. "personal.given_name"
  state: FieldStateKind;
  reason: string; // stable code, "" when none (verify.ts reasons, "portal:<text>")
  placed: boolean; // a mark is on the page for it (Task 3 sets this)
  theirs?: boolean; // portal_error on a value the student typed or changed
  /** Set by the worker from its own cached packet, never by a page (§7.2). */
  offer?: { value: string; source_kind: string };
  upload_kind?: string;
  expired_on?: string;
}

/** What the dock renders. The panel owns the DOM; this is all it is given. */
export interface DockState {
  applicationId: string | null;
  status:
    | "idle" | "pairing" | "ready" | "filling" | "blocked" | "done" | "review"
    | "login" | "stopped";
  message: string;
  /** The panel language the student chose; the content script labels follow it. */
  language?: "az" | "tr" | "ru" | "en";
  fields: FieldView[];
  /** Which page of the form, in the order the student first reached it (the worker counts). */
  page?: number;
  /** The portal tab this dock drives, set when a START_FILL opens it. The
   *  panel asks for `${origin}/*` in its Start click, under the student's gesture. */
  binding?: { tabId: number; origin: string } | null;
  documents: { filename: string; state: "attached" | "manual"; note?: string }[];
  /** The packet's own notes (service_worker.ts keeps no others). */
  notes?: PacketNote[];
  /** Documents whose box the student picks (plan 5). Descriptions are page text. */
  choices?: { filename: string; options: { selector: string; description: string }[] }[];
  /** The registration-mail question (spec §2a), or null when nothing is asked.
   *  Set by the service worker when the server says the mailbox has not
   *  answered; cleared when the student answers. */
  registration: { applicationId: string; portalHost: string; address: string } | null;
  /** A verification code the co-pilot could not type: shown in the panel only
   *  (spec §6). Cleared on the next Start and the next watch. */
  code?: string | null;
  /** The domain that mailed `code`: the panel names the portal it is for. */
  code_from?: string | null;
  /** Bench mode (plan 6): set only when the server lists forms for this device. */
  bench?: { forms: { id: string; portal_host: string; form_url: string }[] } | null;
  /** The last "Record this page" press: whether it was kept. */
  bench_last?: { ok: boolean } | null;
}

/** A portal tab opened for one application (service_worker.ts, storage.session
 *  "bindings", keyed by tabId). Content is injected only into this tab, only on
 *  `origin`, only while `active` (Start pressed, not stopped) and a panel is open. */
export interface Binding {
  tabId: number;
  applicationId: string;
  portalFormId: string;
  origin: string;
  active: boolean;
  /** Set by Stop: the tab's panel stays off on every later page load. */
  stopped?: true;
  /** Paths in the order first reached; the dock's "Page N" is an index into it. */
  pages: string[];
  /** We handed this tab a login and it has not reached the form since. A flag
   *  only: the username and password are never stored. */
  loginTyped?: boolean;
}

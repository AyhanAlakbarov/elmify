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
}

export interface PacketDocument {
  filename: string;
  download_path: string;
  draft_id: string;
}

export interface FillPacket {
  application_id: string;
  portal_form_id: string;
  field_map_version: number;
  form_url: string;
  entries: PacketField[];
  documents: PacketDocument[];
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
}

/** How the extension knows a portal refused the tagged address. Mirrors
 *  apps/portals/ext_api.py::_REJECTION_EVIDENCE; a test pins it. Every kind
 *  is evidence about this student's account only, never the portal's shared
 *  status. */
export type RejectionEvidence = "form" | "page" | "after_submit" | "student";

/** What the dock renders. The panel owns the DOM; this is all it is given. */
export interface DockState {
  applicationId: string | null;
  status: "idle" | "pairing" | "ready" | "filling" | "blocked" | "done";
  filled: string[];
  /** Fields the extension refused to type, and why. The student does these. */
  yourTurn: { label: string; reason: string }[];
  mismatches: { label: string; expected: string; actual: string }[];
  message: string;
  /** The registration-mail question (spec §2a), or null when nothing is asked.
   *  Set by the service worker when the server says the mailbox has not
   *  answered; cleared when the student answers. */
  registration: { applicationId: string; portalHost: string; address: string } | null;
}

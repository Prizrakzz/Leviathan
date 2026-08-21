/* AUTO-GENERATED from src/api/openapi.json — do not edit. Run `npm run gen:types`. */
export interface paths {
    "/healthz": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Healthz */
        get: operations["healthz_healthz_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/respond": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Respond Route */
        post: operations["respond_route_v1_respond_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/respond/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Respond Stream
         * @description SSE wrapper: respond() runs in a worker thread; the stream relays each `on_stage` tick as its own
         *     `stage` event, then the single terminal `result` (or `error`).
         *
         *     `mode` (D-AM-9) is the reasoning-scale query param, the GET twin of Ask.mode -- untyped for the
         *     same reason (unknown -> standard + stamp, never a 422 on a streamed desk turn).
         */
        get: operations["respond_stream_v1_respond_stream_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/credits": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Credits Route
         * @description {remaining, limit, reset_at} — what the credits badge renders, and what the FE re-reads after a
         *     submit or a 429 (the /v1/dossier/quota pattern, generalized). FREE: identity-gated, no model call,
         *     and explicitly NOT the turn quota — reading a counter is not a use of it.
         *
         *     DARK IS A 404, not a zero (the dossier-gate idiom, and the shape api/credits.ts already codes
         *     against): with `GRAPHRAG_CREDITS` off nothing is metered, so there is no meter to report and the FE
         *     renders no badge at all. A 500 would say something different — that the feature exists and broke.
         *
         *     FAIL-OPEN on any store error: a badge that cannot read the counter shows the full grant rather than
         *     telling a paying user they have nothing left.
         */
        get: operations["credits_route_v1_credits_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/graph/{contract}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Graph Route */
        get: operations["graph_route_v1_graph__contract__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/convergence": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Convergence Route */
        get: operations["convergence_route_v1_convergence_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/regimes/{contract}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Regimes Route */
        get: operations["regimes_route_v1_regimes__contract__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/series/{table}/{metric}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Series Route */
        get: operations["series_route_v1_series__table___metric__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Events Route */
        get: operations["events_route_v1_events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/citation/pdf": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Citation Pdf Route
         * @description Resolve a document citation's `locator` (source_key + optional snippet/char offsets/offset_kind) to a
         *     presigned source-PDF url + the best 1-indexed page (6.5) + the Phase-F highlight strings (span/sentence,
         *     null unless the offsets are pin-point kinds on a native PDF). Identity-gated like the other read routes.
         *     Kill-switch `GRAPHRAG_PDF_LINKS` (default ON, mirroring GRAPHRAG_SUGGEST) -> 404 when off, so the FE hides
         *     the affordance with no redeploy. Never 500: a resolver miss degrades to page=null with the url still set;
         *     a MISSING document.json is the only 404 the resolver itself triggers.
         */
        get: operations["citation_pdf_route_v1_citation_pdf_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/suggest": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Suggest Route
         * @description Up to 3 GROUNDED follow-up questions for the completed turn (or starters for `{}`). Fired once per
         *     turn BY THE CLIENT; identity-gated but NEVER the turn quota — a separate namespaced daily counter caps
         *     the Haiku spend, and every failure mode degrades to `[]` (chips are a nicety, never an error state).
         *     D-SG S2: 3 is a TARGET reached by over-generation, never a guarantee reached by padding — on shortfall
         *     the row renders fewer.
         */
        post: operations["suggest_route_v1_suggest_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/gallery": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Gallery Route
         * @description Curated starters for the empty state. Identity-gated like every other read, and FREE — no model call
         *     and NO quota of any kind (unlike /v1/suggest, which spends one per turn). The catalog is the suggester's
         *     own `_suggest_catalog` with an empty scope (global top-N closest to firing): reusing it keeps ONE
         *     definition of what is answerable, including the per-pair census gate. That also means the catalog flag
         *     and the convergence warmer govern here too — with either off the catalog is None and the route serves
         *     the unfilled templates, which is a legible fallback rather than a failure.
         *
         *     D-UX-1 makes the same read serve the EDITABLE library as well as the landing page: each item carries its
         *     raw `template` plus the `slots` it was filled with, and the response carries the `vocab` those slots were
         *     drawn from. Additive only — `items[].question` and `catalog_warm` are byte-identical to D-AM-16.
         */
        get: operations["gallery_route_v1_gallery_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/profile": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Get Profile Route
         * @description The signed-in user's own profile — identity claims + facts + the onboarding flag. Auth-gated; a
         *     missing record returns identity-only defaults (facts={}, onboarded=false).
         */
        get: operations["get_profile_route_v1_profile_get"];
        /**
         * Put Profile Route
         * @description Update the user's facts and/or onboarding flag — a PARTIAL update (omitted fields unchanged). Facts
         *     are normalized server-side before the write; the fresh profile is returned. A genuine store failure
         *     propagates (the client must know a save didn't persist — unlike the fire-and-forget touch_profile).
         */
        put: operations["put_profile_route_v1_profile_put"];
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/notifications": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List Notifications Route
         * @description The signed-in user's daily-digest notifications, newest-first. Empty list when the feature is off or
         *     the user has none — the bell degrades to 'no notifications' cleanly, never a 404. Preferences-adjacent
         *     (never the answer/evidence path), so the PIT firewall is untouched. No quota (reads are free).
         */
        get: operations["list_notifications_route_v1_notifications_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/notifications/{notif_id}/seen": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Mark Notification Seen Route
         * @description Mark one notification read (idempotent). 404-free AND upsert-free: the store's conditional UpdateItem
         *     (attribute_exists(sk)) makes an unknown/garbage id a swallowed no-op, so a POST can never CREATE a
         *     body-less notif# item that escapes TTL. Always 200.
         */
        post: operations["mark_notification_seen_route_v1_notifications__notif_id__seen_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/share": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /** Share Create */
        post: operations["share_create_v1_share_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/share/{share_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Share Get */
        get: operations["share_get_v1_share__share_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/threads": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List */
        get: operations["_list_v1_threads_get"];
        put?: never;
        /** Put */
        post: operations["_put_v1_threads_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/threads/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Del */
        delete: operations["_del_v1_threads__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/watchlists": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List */
        get: operations["_list_v1_watchlists_get"];
        put?: never;
        /** Put */
        post: operations["_put_v1_watchlists_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/watchlists/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Del */
        delete: operations["_del_v1_watchlists__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workspaces": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List */
        get: operations["_list_v1_workspaces_get"];
        put?: never;
        /** Put */
        post: operations["_put_v1_workspaces_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/workspaces/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Del */
        delete: operations["_del_v1_workspaces__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/artifacts": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** List */
        get: operations["_list_v1_artifacts_get"];
        put?: never;
        /** Put */
        post: operations["_put_v1_artifacts_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/artifacts/{item_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        post?: never;
        /** Del */
        delete: operations["_del_v1_artifacts__item_id__delete"];
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/threads/{thread_id}/turns": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Thread Turns
         * @description Durable per-thread history (design §3.1) — the PIT-safe turn records for a thread, oldest-first.
         *     Conclusions + citation refs only; evidence is never persisted (re-derived on re-run).
         */
        get: operations["thread_turns_v1_threads__thread_id__turns_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/dossier": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Dossier Create
         * @description Accept a deep-research dossier -> 202 {dossier_id, plan_pending: true}.
         *
         *     QUOTA IS CHARGED HERE, at ACCEPTANCE, never at completion: two submissions racing on the last slot
         *     must not both pass, and the atomic conditional counter can only guarantee that at the gate. A job
         *     that later FAILS refunds; a PARTIAL one does not (it delivered a document and spent real money).
         *
         *     ONE as-of is stamped now and governs every sub-query (PIT by construction). An unparseable one is
         *     rejected loudly rather than silently defaulted — a dossier is 20 minutes and 5-12 turns of spend,
         *     which is the one place in this API where a typo must not be absorbed.
         */
        post: operations["dossier_create_v1_dossier_post"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/dossier/quota": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dossier Quota
         * @description {remaining, limit, reset_at} — what the mode picker's badge renders. Free, no model call, no
         *     turn quota (a read of a counter is not a use of it).
         */
        get: operations["dossier_quota_v1_dossier_quota_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/dossier/{dossier_id}": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dossier Get
         * @description Job state. Owner-scoped by construction: the record is read out of the caller's OWN partition,
         *     so another user's id is simply not there (404) — the artifacts privacy posture, not a new one.
         */
        get: operations["dossier_get_v1_dossier__dossier_id__get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/v1/dossier/{dossier_id}/events": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Dossier Events
         * @description SSE progress stream — the `respond_stream` idiom (queue relay, 10s keepalive comment, terminal
         *     event closes), with ONE difference that matters: the job is not owned by this request, so the
         *     stream REPLAYS the events already recorded before it attaches. A client that connects after the
         *     plan landed still sees the plan; a client that connects after the job finished gets the whole
         *     history and an immediate close. Both are the same code path.
         *
         *     A dossier that is not live in THIS process (a restart, or another task) replays its persisted log
         *     and closes — never a stream that hangs forever waiting for a thread that does not exist.
         */
        get: operations["dossier_events_v1_dossier__dossier_id__events_get"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /** Ask */
        Ask: {
            /** Question */
            question: string;
            /** Session Id */
            session_id?: string | null;
            /** Asof */
            asof?: string | null;
            /**
             * Context
             * @default []
             */
            context: components["schemas"]["ContextAttachment"][];
            /** Mode */
            mode?: string | null;
            /** Turn Id */
            turn_id?: string | null;
        };
        /**
         * CitationPdf
         * @description The 6.5 click-to-page resolver result the PdfModal binds to: a presigned URL to the SOURCE document,
         *     the best-guess 1-indexed `page` (null when unresolvable -- the modal opens at the top with a 'page unknown'
         *     banner), the raw doc `kind` (pdf/html/txt/other) so the FE picks a viewer, and the presign TTL in seconds.
         *     Phase F adds the highlight strings: `span` = the verbatim pin-point the offsets name in the server's
         *     full_text (the FE searches the pdf.js text layer for it -- offsets themselves cannot cross extractors),
         *     and `sentence` = its D12 containing-sentence expansion (what glows). Both null unless the citation
         *     carries pin-point offsets (exact/exact_ws) on a native PDF -- block offsets and scanned docs stay
         *     page-jump-only by design, and a null degrades to today's behaviour, never errors.
         *     Never an error shape -- a resolver miss degrades to page=null with the url still set; the route 404s ONLY
         *     when the document.json itself is gone (or the GRAPHRAG_PDF_LINKS kill-switch is off).
         */
        CitationPdf: {
            /** Url */
            url: string;
            /** Page */
            page?: number | null;
            /** Kind */
            kind: string;
            /** Expires In */
            expires_in: number;
            /** Span */
            span?: string | null;
            /** Sentence */
            sentence?: string | null;
        };
        /**
         * ContextAttachment
         * @description One typed 'point at the graph' gesture attached to a turn (node/edge/event/series). The SERVER
         *     re-derives everything trust-bearing: node/edge ids are validated against the causal graph, the edge
         *     mechanism is looked up server-side, and an event's driver_id is CODE-mapped from its enum-locked
         *     event_type — the client's driver_id/mechanism strings are ignored by the resolver (injection posture).
         *     A future-dated event (date > the final as-of) is fully withheld with a visible note (PIT).
         *
         *     D-UX-4 `series` is a CHART LOCATOR and nothing else — {table, metric, commodity?, country?,
         *     contract_month?}, i.e. exactly /v1/series' arguments MINUS the as-of. Carrying no as-of and no points
         *     is the whole design: the attachment steers (which series the desk is looking at), the numbers agent
         *     re-reads it under the NEW turn's own as-of, so an attached chart can never carry a value read at some
         *     other horizon into a later answer.
         */
        ContextAttachment: {
            /**
             * Type
             * @enum {string}
             */
            type: "node" | "edge" | "event" | "series";
            /** Contract */
            contract?: string | null;
            /** Driver Id */
            driver_id?: string | null;
            /** Source */
            source?: string | null;
            /** Target */
            target?: string | null;
            /** Event Type */
            event_type?: string | null;
            /** Commodity */
            commodity?: string | null;
            /** Country */
            country?: string | null;
            /** Summary */
            summary?: string | null;
            /** Date */
            date?: string | null;
            /** Table */
            table?: string | null;
            /** Metric */
            metric?: string | null;
            /** Contract Month */
            contract_month?: string | null;
            /** Label */
            label?: string | null;
        };
        /** ConvergenceMatrix */
        ConvergenceMatrix: {
            /** Asof */
            asof: string;
            /** Graph Version */
            graph_version?: string | null;
            /** Rows */
            rows: components["schemas"]["ConvergenceRow"][];
        };
        /** ConvergenceRow */
        ConvergenceRow: {
            /** Contract */
            contract: string;
            /** Regimes */
            regimes: components["schemas"]["RegimeCard"][];
            /** Drivers */
            drivers: components["schemas"]["DriverSignal"][];
        };
        /** DossierIn */
        DossierIn: {
            /** Question */
            question: string;
            /** Asof */
            asof?: string | null;
        };
        /** DriverSignal */
        DriverSignal: {
            /** Id */
            id: string;
            /**
             * Live
             * @default false
             */
            live: boolean;
            /** Verdict */
            verdict?: string | null;
            /** Z */
            z?: number | null;
            /** Value */
            value?: unknown | null;
            /**
             * Unit
             * @default
             */
            unit: string;
            /** Ref */
            ref?: string | null;
            /**
             * Knowledge Date
             * @default
             */
            knowledge_date: string;
        } & {
            [key: string]: unknown;
        };
        /** EventItem */
        EventItem: {
            /**
             * Source
             * @default
             */
            source: string;
            /**
             * Title
             * @default
             */
            title: string;
            /**
             * Summary
             * @default
             */
            summary: string;
            /**
             * Url
             * @default
             */
            url: string;
            /**
             * Date
             * @default
             */
            date: string;
            /** Driver Id */
            driver_id?: string | null;
            /** Commodity */
            commodity?: string | null;
        } & {
            [key: string]: unknown;
        };
        /** EventsFeed */
        EventsFeed: {
            /** Contract */
            contract?: string | null;
            /** Asof */
            asof: string;
            /** Live */
            live: boolean;
            /** Events */
            events: components["schemas"]["EventItem"][];
        };
        /**
         * Gallery
         * @description The whole gallery in one free read. `catalog_warm` distinguishes 'filled from live data' from the
         *     template fallback, so a blank-slot gallery is legible as a cold cache rather than a bug. Never an error
         *     shape: an unreadable config degrades to `items: []` (no starter row), never a 500 on the landing page.
         */
        Gallery: {
            /**
             * Items
             * @default []
             */
            items: components["schemas"]["GalleryItem"][];
            /**
             * Catalog Warm
             * @default false
             */
            catalog_warm: boolean;
            vocab?: components["schemas"]["GalleryVocab"];
        };
        /**
         * GalleryItem
         * @description One curated starter. `question` is the AUTHORED template with its slots filled from the warm
         *     convergence catalog; `filled` is false when the catalog was cold, in which case `question` is the raw
         *     template and its `{contract}`/`{regime}`/`{pair}` blanks are the user's to complete. `rc_target` is the
         *     response contract the wording selects (pinned by test) — carried on the wire as honest provenance for
         *     the eval/debug lane, not read by the UI.
         *
         *     D-UX-1 adds the two fields the EDITABLE template library needs, both derived from what the fill already
         *     computed (no new server work, no new data): `template` is the raw authored wording WITH its braces, and
         *     `slots` are the values this row was filled with. `question` stays the product — and stays derivable:
         *     substituting `slots` into `template` reproduces it byte-for-byte (pinned), so an FE that re-fills the
         *     template starts from exactly the question the gallery advertises, with the TRUE near-row pairing intact,
         *     and only diverges where the analyst edits a slot.
         */
        GalleryItem: {
            /** Id */
            id: string;
            /** Category */
            category: string;
            /** Question */
            question: string;
            /**
             * Rc Target
             * @default default
             */
            rc_target: string;
            /**
             * Filled
             * @default true
             */
            filled: boolean;
            /**
             * Template
             * @default
             */
            template: string;
            /**
             * Slots
             * @default {}
             */
            slots: {
                [key: string]: string;
            };
        };
        /**
         * GalleryVocab
         * @description D-UX-1 — the raw slot vocabularies behind the filled examples, so the FE's per-slot combobox can offer
         *     what the engine can answer instead of the analyst guessing. Same warm-catalog read as the items (no
         *     model, no quota); `pairs` carries ONLY the census-realizable set, so the gate that fences the templates
         *     fences the dropdown too. Every list is empty on a cold catalog — an empty dropdown that still accepts
         *     free typing is the honest degradation.
         */
        GalleryVocab: {
            /**
             * Contracts
             * @default []
             */
            contracts: string[];
            /**
             * Regimes
             * @default []
             */
            regimes: string[];
            /**
             * Pairs
             * @default []
             */
            pairs: string[];
        };
        /** GraphEdge */
        GraphEdge: {
            /** Source */
            source: string;
            /** Target */
            target: string;
            /** Edge Type */
            edge_type: string;
            /** Sign */
            sign?: string | null;
            /** Lag */
            lag?: string | null;
            /** Mechanism */
            mechanism?: string | null;
            /** Confidence */
            confidence?: string | null;
        } & {
            [key: string]: unknown;
        };
        /** GraphNode */
        GraphNode: {
            /** Id */
            id: string;
            /** Kind */
            kind: string;
            /** Contract */
            contract: string;
            /** Label */
            label?: string | null;
            /** Silver Status */
            silver_status?: string | null;
            /** Confidence */
            confidence?: string | null;
            /** Active */
            active?: boolean | null;
        } & {
            [key: string]: unknown;
        };
        /** GraphTopology */
        GraphTopology: {
            /** Contract */
            contract: string;
            /** Graph Version */
            graph_version?: string | null;
            /** Asof */
            asof?: string | null;
            /** Nodes */
            nodes: components["schemas"]["GraphNode"][];
            /** Edges */
            edges: components["schemas"]["GraphEdge"][];
        };
        /** HTTPValidationError */
        HTTPValidationError: {
            /** Detail */
            detail?: components["schemas"]["ValidationError"][];
        };
        /** ItemIn */
        ItemIn: {
            /** Id */
            id?: string | null;
            /**
             * Body
             * @default {}
             */
            body: {
                [key: string]: unknown;
            };
        };
        /**
         * NotificationItem
         * @description One fanned-out daily-digest notification (auth-gated GET /v1/notifications). Carries the NARROW P2
         *     event-attachment projection (event_type/commodity/date/summary/country) PLUS server-built display
         *     artifacts (label + templated analogue query) the FE cannot synthesize, since an event chip never
         *     receives driver_id on the wire. The stored body also carries an `event` LiveEvent audit blob — kept
         *     OFF this model on purpose: pydantic's default extra='ignore' (NO model_config; do NOT use _RICH,
         *     which is extra='allow') silently drops it, the belt to the route's server-side projection.
         */
        NotificationItem: {
            /** Notif Id */
            notif_id: string;
            /** Created At */
            created_at: string;
            /**
             * Seen
             * @default false
             */
            seen: boolean;
            /** Event Type */
            event_type: string;
            /** Commodity */
            commodity: string;
            /** Date */
            date?: string | null;
            /**
             * Summary
             * @default
             */
            summary: string;
            /** Country */
            country?: string | null;
            /** Label */
            label: string;
            /** Query */
            query: string;
            /** Driver Id */
            driver_id?: string | null;
        };
        /**
         * Profile
         * @description The signed-in user's own profile (auth-gated GET /v1/profile). Identity claims (name/email) mirror
         *     the ID token; `facts` is the user-authored preference dict (markets/regions/seat/notes) that personalizes
         *     the query suggester — PREFERENCES, never evidence, so the PIT firewall is untouched. `onboarded` gates the
         *     first-run flow. turn_count/first_seen are display-only bookkeeping.
         */
        Profile: {
            /** Sub */
            sub?: string | null;
            /** Email */
            email?: string | null;
            /** Name */
            name?: string | null;
            /**
             * Facts
             * @default {}
             */
            facts: {
                [key: string]: unknown;
            };
            /**
             * Onboarded
             * @default false
             */
            onboarded: boolean;
            /**
             * Turn Count
             * @default 0
             */
            turn_count: number;
            /** First Seen */
            first_seen?: string | null;
            /** Last Seen */
            last_seen?: string | null;
        } & {
            [key: string]: unknown;
        };
        /**
         * ProfileUpdate
         * @description PUT /v1/profile body — a partial update. `facts` is normalized server-side (known keys only, capped
         *     counts/lengths); `onboarded` flips the first-run gate. Omitted fields are left unchanged.
         */
        ProfileUpdate: {
            /** Facts */
            facts?: {
                [key: string]: unknown;
            } | null;
            /** Onboarded */
            onboarded?: boolean | null;
        };
        /** RegimeCard */
        RegimeCard: {
            /** Name */
            name: string;
            /** Direction */
            direction: string;
            /** Matched */
            matched: string[];
            /** Threshold */
            threshold: number;
            /** Fired */
            fired: boolean;
            /** N Active */
            n_active: number;
            /** Proximity */
            proximity: number;
        };
        /** Series */
        Series: {
            /** Table */
            table: string;
            /** Metric */
            metric: string;
            /** Commodity */
            commodity?: string | null;
            /** Asof */
            asof: string;
            /**
             * Unit
             * @default
             */
            unit: string;
            /** Points */
            points: {
                [key: string]: unknown;
            }[];
        };
        /** ShareIn */
        ShareIn: {
            /** Question */
            question: string;
            /** Asof */
            asof?: string | null;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
        };
        /** ShareRef */
        ShareRef: {
            /** Id */
            id: string;
            /** Url */
            url: string;
        };
        /** ShareSnapshot */
        ShareSnapshot: {
            /** Id */
            id: string;
            /** Question */
            question: string;
            /** Asof */
            asof?: string | null;
            /** Graph Version */
            graph_version?: string | null;
            /** Chunk Version */
            chunk_version?: string | null;
            /** Calibration Version */
            calibration_version?: string | null;
            /** Created At */
            created_at: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
        } & {
            [key: string]: unknown;
        };
        /**
         * SuggestRequest
         * @description The turn packet the CLIENT sends after a completed turn (or `{}` on thread start). The server
         *     enriches with profile facts + cached news headlines — it never re-reads evidence or session state.
         */
        SuggestRequest: {
            /** Thread Id */
            thread_id?: string | null;
            /** Question */
            question?: string | null;
            /** Tldr */
            tldr?: string | null;
            /**
             * Contracts
             * @default []
             */
            contracts: string[];
            /** Intent */
            intent?: string | null;
            /** Asof */
            asof?: string | null;
        };
        /**
         * SuggestResponse
         * @description Up to 3 grounded follow-up questions (or [] — over-cap, kill-switch, cold catalog and parse failure
         *     all degrade to empty; suggestions are a nicety and must never surface an error).
         */
        SuggestResponse: {
            /**
             * Suggestions
             * @default []
             */
            suggestions: string[];
        };
        /** ThreadTurns */
        ThreadTurns: {
            /** Thread Id */
            thread_id: string;
            /**
             * Turns
             * @default []
             */
            turns: components["schemas"]["TurnRecord"][];
        };
        /**
         * TurnRecord
         * @description One durable turn in a thread — the CONCLUSION only (PIT firewall): question + synthesized answer +
         *     citation refs + the as-of/graph it was made under. NEVER carries retrieved evidence or raw number rows;
         *     those re-derive under the turn's own as-of if it is re-run.
         */
        TurnRecord: {
            /** Question */
            question?: string | null;
            /** Answer */
            answer?: string | null;
            /** Structured */
            structured?: {
                [key: string]: unknown;
            } | null;
            /** Asof */
            asof?: string | null;
            /**
             * Sources
             * @default []
             */
            sources: {
                [key: string]: unknown;
            }[];
            /** Graph Version */
            graph_version?: string | null;
            /** Chunk Version */
            chunk_version?: string | null;
            /** Calibration Version */
            calibration_version?: string | null;
            /** Contract */
            contract?: string | null;
            /**
             * Contracts
             * @default []
             */
            contracts: string[];
            /** Intent */
            intent?: string | null;
            /** Model */
            model?: string | null;
            /** Ts */
            ts?: string | null;
        } & {
            [key: string]: unknown;
        };
        /** ValidationError */
        ValidationError: {
            /** Location */
            loc: (string | number)[];
            /** Message */
            msg: string;
            /** Error Type */
            type: string;
        };
    };
    responses: never;
    parameters: never;
    requestBodies: never;
    headers: never;
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    healthz_healthz_get: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
        };
    };
    respond_route_v1_respond_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["Ask"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    respond_stream_v1_respond_stream_get: {
        parameters: {
            query: {
                question: string;
                session_id?: string | null;
                asof?: string | null;
                context?: string | null;
                mode?: string | null;
                turn_id?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    credits_route_v1_credits_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    graph_route_v1_graph__contract__get: {
        parameters: {
            query?: {
                asof?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                contract: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["GraphTopology"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    convergence_route_v1_convergence_get: {
        parameters: {
            query?: {
                asof?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConvergenceMatrix"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    regimes_route_v1_regimes__contract__get: {
        parameters: {
            query?: {
                asof?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                contract: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ConvergenceRow"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    series_route_v1_series__table___metric__get: {
        parameters: {
            query?: {
                commodity?: string | null;
                country?: string | null;
                asof?: string | null;
                contract_month?: string | null;
                agg?: string;
            };
            header?: {
                authorization?: string | null;
            };
            path: {
                table: string;
                metric: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Series"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    events_route_v1_events_get: {
        parameters: {
            query?: {
                contract?: string | null;
                asof?: string | null;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["EventsFeed"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    citation_pdf_route_v1_citation_pdf_get: {
        parameters: {
            query: {
                source_key: string;
                snippet?: string | null;
                char_start?: number | null;
                offset_kind?: string | null;
                char_end?: number | null;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CitationPdf"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    suggest_route_v1_suggest_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["SuggestRequest"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["SuggestResponse"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    gallery_route_v1_gallery_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Gallery"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    get_profile_route_v1_profile_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Profile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    put_profile_route_v1_profile_put: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ProfileUpdate"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["Profile"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    list_notifications_route_v1_notifications_get: {
        parameters: {
            query?: {
                unseen_only?: boolean;
            };
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["NotificationItem"][];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    mark_notification_seen_route_v1_notifications__notif_id__seen_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                notif_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    share_create_v1_share_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ShareIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ShareRef"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    share_get_v1_share__share_id__get: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                share_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ShareSnapshot"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _list_v1_threads_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _put_v1_threads_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ItemIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _del_v1_threads__item_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _list_v1_watchlists_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _put_v1_watchlists_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ItemIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _del_v1_watchlists__item_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _list_v1_workspaces_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _put_v1_workspaces_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ItemIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _del_v1_workspaces__item_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _list_v1_artifacts_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _put_v1_artifacts_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ItemIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    _del_v1_artifacts__item_id__delete: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                item_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    thread_turns_v1_threads__thread_id__turns_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                thread_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ThreadTurns"];
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dossier_create_v1_dossier_post: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["DossierIn"];
            };
        };
        responses: {
            /** @description Successful Response */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dossier_quota_v1_dossier_quota_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dossier_get_v1_dossier__dossier_id__get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                dossier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        [key: string]: unknown;
                    };
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
    dossier_events_v1_dossier__dossier_id__events_get: {
        parameters: {
            query?: never;
            header?: {
                authorization?: string | null;
            };
            path: {
                dossier_id: string;
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Successful Response */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": unknown;
                };
            };
            /** @description Validation Error */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HTTPValidationError"];
                };
            };
        };
    };
}

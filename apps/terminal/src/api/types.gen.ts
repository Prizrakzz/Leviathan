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
         * @description Resolve a document citation's `locator` (source_key + optional snippet/char_start/offset_kind) to a
         *     presigned source-PDF url + the best 1-indexed page (6.5). Identity-gated like the other read routes.
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
         * @description 3-4 follow-up questions for the completed turn (or starters for `{}`). Fired once per turn BY THE
         *     CLIENT; identity-gated but NEVER the turn quota — a separate namespaced daily counter caps the Haiku
         *     spend, and every failure mode degrades to `[]` (chips are a nicety, never an error state).
         */
        post: operations["suggest_route_v1_suggest_post"];
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
        };
        /**
         * CitationPdf
         * @description The 6.5 click-to-page resolver result the PdfModal binds to: a presigned URL to the SOURCE document,
         *     the best-guess 1-indexed `page` (null when unresolvable -- the modal opens at the top with a 'page unknown'
         *     banner), the raw doc `kind` (pdf/html/txt/other) so the FE picks a viewer, and the presign TTL in seconds.
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
         * @description 3-4 follow-up questions (or [] — over-cap, kill-switch, parse failure all degrade to empty;
         *     suggestions are a nicety and must never surface an error).
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
}

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
            /** Created At */
            created_at: string;
            /** Payload */
            payload: {
                [key: string]: unknown;
            };
        } & {
            [key: string]: unknown;
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
            header?: never;
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
            header?: never;
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
            };
            header?: never;
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

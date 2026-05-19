/** Shared TypeScript types */

export interface User {
    id: string;
    username: string;
    email: string;
    display_name: string;
    avatar_url?: string;
    role: 'platform_admin' | 'org_admin' | 'agent_admin' | 'member';
    is_platform_admin?: boolean;
    tenant_id?: string;
    title?: string;
    feishu_open_id?: string;
    is_active: boolean;
    email_verified?: boolean;
    created_at: string;
}

export interface Agent {
    id: string;
    name: string;
    avatar_url?: string;
    role_description: string;
    bio?: string;
    status: 'creating' | 'running' | 'idle' | 'stopped' | 'error';
    creator_id: string;
    primary_model_id?: string;
    fallback_model_id?: string;
    autonomy_policy: Record<string, string>;
    tokens_used_today: number;
    tokens_used_month: number;
    tokens_used_total?: number;
    cache_read_tokens_today?: number;
    cache_read_tokens_month?: number;
    cache_read_tokens_total?: number;
    cache_creation_tokens_today?: number;
    cache_creation_tokens_month?: number;
    cache_creation_tokens_total?: number;
    max_tokens_per_day?: number;
    max_tokens_per_month?: number;
    heartbeat_enabled: boolean;
    heartbeat_interval_minutes: number;
    heartbeat_active_hours: string;
    last_heartbeat_at?: string;
    timezone?: string;
    context_window_size?: number;
    agent_type?: 'native' | 'opencode';
    opencode_last_seen?: string;
    unread_count?: number;
    // True when the viewing user has already been onboarded to this agent.
    // Defaults to true on list endpoints that don't compute per-viewer state.
    onboarded_for_me?: boolean;
    created_at: string;
    last_active_at?: string;
}

export interface Task {
    id: string;
    agent_id: string;
    title: string;
    description?: string;
    type: 'todo' | 'supervision';
    status: 'pending' | 'doing' | 'done' | 'paused';
    priority: 'low' | 'medium' | 'high' | 'urgent';
    assignee: string;
    created_by: string;
    creator_username?: string;
    due_date?: string;
    supervision_target_name?: string;
    supervision_channel?: string;
    remind_schedule?: string;
    created_at: string;
    updated_at: string;
    completed_at?: string;
}

export interface ChatMessage {
    id: string;
    agent_id: string;
    user_id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    created_at: string;
}

export interface MemoryDocument {
    id: string;
    tenant_id?: string;
    agent_id?: string;
    user_id?: string;
    created_by?: string;
    scope: string;
    memory_type: string;
    title: string;
    content: string;
    source_type: string;
    source_ref_id?: string;
    metadata_json: Record<string, any>;
    importance_score: number;
    visibility: string;
    is_verified: boolean;
    created_at: string;
    updated_at: string;
}

export interface MemorySearchItem {
    source: 'memory' | 'golden_example' | 'enterprise_kb';
    score: number;
    title: string;
    content: string;
    memory_id?: string;
    golden_example_id?: string;
    metadata: Record<string, any>;
}

export interface AnswerFeedback {
    id: string;
    message_id: string;
    agent_id: string;
    user_id: string;
    feedback_type: 'upvote' | 'downvote';
    comment?: string;
    corrected_answer?: string;
    question_snapshot?: string;
    normalized_question?: string;
    created_at: string;
    updated_at: string;
}

export interface GoldenExample {
    id: string;
    tenant_id?: string;
    agent_id?: string;
    source_feedback_id?: string;
    question: string;
    normalized_question: string;
    correct_answer: string;
    status: 'pending_review' | 'approved' | 'rejected' | 'active';
    tags: string[];
    review_note?: string;
    reviewed_by?: string;
    reviewed_at?: string;
    created_at: string;
    updated_at: string;
}

export interface KnowledgeGap {
    question_cluster: string;
    frequency: number;
    affected_agent_ids: string[];
    active_example_count: number;
    pending_feedback_count: number;
    suggested_action: string;
    sample_questions: string[];
}

export interface WorkflowDefinition {
    id: string;
    agent_id: string;
    tenant_id?: string;
    created_by: string;
    name: string;
    description?: string;
    status: 'draft' | 'active' | 'archived';
    version: number;
    definition: {
        nodes: Array<{
            key: string;
            type: string;
            title: string;
            x: number;
            y: number;
            config?: Record<string, any>;
        }>;
        edges: Array<{
            id: string;
            source: string;
            target: string;
            label?: string;
        }>;
    };
    canvas_layout: Record<string, any>;
    input_schema: Record<string, any>;
    output_schema: Record<string, any>;
    created_at: string;
    updated_at: string;
}

export interface WorkflowRun {
    id: string;
    workflow_id: string;
    agent_id: string;
    started_by: string;
    trigger_type: string;
    status: 'pending' | 'running' | 'waiting_human' | 'completed' | 'failed' | 'cancelled' | 'rejected';
    input_payload: Record<string, any>;
    context_snapshot: Record<string, any>;
    output_payload: Record<string, any>;
    current_node_key?: string | null;
    error_message?: string | null;
    started_at?: string | null;
    finished_at?: string | null;
    created_at: string;
    updated_at: string;
    node_runs?: Array<{
        id: string;
        node_key: string;
        node_type: string;
        title: string;
        status: string;
        attempt: number;
        input_payload: Record<string, any>;
        output_payload: Record<string, any>;
        error_message?: string | null;
        started_at?: string | null;
        finished_at?: string | null;
    }>;
}

export interface TokenResponse {
    access_token: string;
    token_type: string;
    user: User;
    needs_company_setup?: boolean;
}

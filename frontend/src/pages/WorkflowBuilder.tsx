import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { IconPlayerPlay, IconPlus, IconTrash, IconDeviceFloppy, IconArrowLeft } from '@tabler/icons-react';

import { agentApi, workflowApi } from '../services/api';
import type { WorkflowDefinition, WorkflowRun } from '../types';

type WorkflowNode = {
    key: string;
    type: string;
    title: string;
    x: number;
    y: number;
    config?: Record<string, any>;
};

type WorkflowEdge = {
    id: string;
    source: string;
    target: string;
    label?: string;
};

const NODE_TYPES = ['start', 'task', 'agent', 'tool', 'condition', 'parallel', 'approval', 'end'];

function createDefaultWorkflow(name = 'New Workflow'): Partial<WorkflowDefinition> {
    return {
        name,
        description: '',
        status: 'draft',
        definition: {
            nodes: [
                { key: 'start', type: 'start', title: 'Start', x: 80, y: 120, config: {} },
                { key: 'task_1', type: 'task', title: 'First Task', x: 320, y: 120, config: {} },
                { key: 'end', type: 'end', title: 'End', x: 560, y: 120, config: {} },
            ],
            edges: [
                { id: 'edge_1', source: 'start', target: 'task_1', label: '' },
                { id: 'edge_2', source: 'task_1', target: 'end', label: '' },
            ],
        },
        canvas_layout: { viewport: { x: 0, y: 0, zoom: 1 } },
        input_schema: {},
        output_schema: {},
    };
}

export default function WorkflowBuilder() {
    const { id: agentId = '' } = useParams();
    const navigate = useNavigate();
    const qc = useQueryClient();
    const boardRef = useRef<HTMLDivElement | null>(null);
    const dragRef = useRef<{ key: string; offsetX: number; offsetY: number } | null>(null);

    const { data: agent } = useQuery({
        queryKey: ['agent', agentId],
        queryFn: () => agentApi.get(agentId),
        enabled: !!agentId,
    });
    const { data: workflows = [] } = useQuery({
        queryKey: ['workflows', agentId],
        queryFn: () => workflowApi.list(agentId),
        enabled: !!agentId,
    });

    const [selectedWorkflowId, setSelectedWorkflowId] = useState<string | null>(null);
    const selectedWorkflow = useMemo(
        () => workflows.find((item) => item.id === selectedWorkflowId) || null,
        [workflows, selectedWorkflowId]
    );

    const [draft, setDraft] = useState<Partial<WorkflowDefinition>>(createDefaultWorkflow());
    const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>('task_1');
    const [edgeDraft, setEdgeDraft] = useState({ source: 'task_1', target: 'end', label: '' });
    const [runLoading, setRunLoading] = useState(false);
    const [saveLoading, setSaveLoading] = useState(false);
    const [approvalLoading, setApprovalLoading] = useState<'approve' | 'reject' | null>(null);
    const [runs, setRuns] = useState<WorkflowRun[]>([]);
    const [activeRunId, setActiveRunId] = useState<string | null>(null);

    useEffect(() => {
        if (!selectedWorkflowId && workflows.length) {
            setSelectedWorkflowId(workflows[0].id);
        }
    }, [workflows, selectedWorkflowId]);

    useEffect(() => {
        if (selectedWorkflow) {
            setDraft(JSON.parse(JSON.stringify(selectedWorkflow)));
            setSelectedNodeKey(selectedWorkflow.definition.nodes[0]?.key || null);
            void workflowApi.runs(agentId, selectedWorkflow.id).then((data) => {
                setRuns(data);
                setActiveRunId(data[0]?.id || null);
            });
        } else if (!workflows.length) {
            setDraft(createDefaultWorkflow());
            setRuns([]);
            setActiveRunId(null);
        }
    }, [selectedWorkflow, workflows.length, agentId]);

    useEffect(() => {
        const onMove = (event: PointerEvent) => {
            if (!dragRef.current || !boardRef.current) return;
            const rect = boardRef.current.getBoundingClientRect();
            const x = Math.max(16, event.clientX - rect.left - dragRef.current.offsetX);
            const y = Math.max(16, event.clientY - rect.top - dragRef.current.offsetY);
            setDraft((current) => ({
                ...current,
                definition: {
                    ...(current.definition || { nodes: [], edges: [] }),
                    nodes: ((current.definition?.nodes as WorkflowNode[]) || []).map((node) =>
                        node.key === dragRef.current?.key ? { ...node, x, y } : node
                    ),
                    edges: (current.definition?.edges as WorkflowEdge[]) || [],
                },
            }));
        };
        const onUp = () => {
            dragRef.current = null;
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        return () => {
            window.removeEventListener('pointermove', onMove);
            window.removeEventListener('pointerup', onUp);
        };
    }, []);

    const nodes = ((draft.definition?.nodes as WorkflowNode[]) || []);
    const edges = ((draft.definition?.edges as WorkflowEdge[]) || []);
    const selectedNode = nodes.find((node) => node.key === selectedNodeKey) || null;
    const activeRun = runs.find((run) => run.id === activeRunId) || null;

    const saveWorkflow = async (): Promise<string | null> => {
        setSaveLoading(true);
        try {
            const payload = {
                name: draft.name,
                description: draft.description,
                status: draft.status || 'draft',
                definition: draft.definition,
                canvas_layout: draft.canvas_layout || {},
                input_schema: draft.input_schema || {},
                output_schema: draft.output_schema || {},
            };
            if (selectedWorkflowId) {
                await workflowApi.update(agentId, selectedWorkflowId, payload);
                await qc.invalidateQueries({ queryKey: ['workflows', agentId] });
                return selectedWorkflowId;
            }
            const created = await workflowApi.create(agentId, payload);
            setSelectedWorkflowId(created.id);
            await qc.invalidateQueries({ queryKey: ['workflows', agentId] });
            return created.id;
        } finally {
            setSaveLoading(false);
        }
    };

    const createWorkflow = () => {
        setSelectedWorkflowId(null);
        setDraft(createDefaultWorkflow(`Workflow ${workflows.length + 1}`));
        setSelectedNodeKey('task_1');
        setRuns([]);
        setActiveRunId(null);
    };

    const removeWorkflow = async () => {
        if (!selectedWorkflowId) return;
        await workflowApi.delete(agentId, selectedWorkflowId);
        await qc.invalidateQueries({ queryKey: ['workflows', agentId] });
        setSelectedWorkflowId(null);
    };

    const addNode = () => {
        let count = nodes.length + 1;
        let key = `node_${count}`;
        const existingKeys = new Set(nodes.map((node) => node.key));
        while (existingKeys.has(key)) {
            count += 1;
            key = `node_${count}`;
        }
        const nextNode: WorkflowNode = {
            key,
            type: 'task',
            title: `Node ${count}`,
            x: 180 + (count % 4) * 180,
            y: 80 + Math.floor(count / 4) * 140,
            config: {},
        };
        setDraft((current) => ({
            ...current,
            definition: {
                ...(current.definition || { nodes: [], edges: [] }),
                nodes: [...(((current.definition?.nodes as WorkflowNode[]) || [])), nextNode],
                edges: (current.definition?.edges as WorkflowEdge[]) || [],
            },
        }));
        setSelectedNodeKey(key);
        setEdgeDraft((current) => ({ ...current, target: key }));
    };

    const removeNode = () => {
        if (!selectedNodeKey) return;
        setDraft((current) => ({
            ...current,
            definition: {
                ...(current.definition || { nodes: [], edges: [] }),
                nodes: (((current.definition?.nodes as WorkflowNode[]) || []).filter((node) => node.key !== selectedNodeKey)),
                edges: (((current.definition?.edges as WorkflowEdge[]) || []).filter(
                    (edge) => edge.source !== selectedNodeKey && edge.target !== selectedNodeKey
                )),
            },
        }));
        setSelectedNodeKey(null);
    };

    const addEdge = () => {
        if (!edgeDraft.source || !edgeDraft.target || edgeDraft.source === edgeDraft.target) return;
        const edge: WorkflowEdge = {
            id: `edge_${Date.now()}`,
            source: edgeDraft.source,
            target: edgeDraft.target,
            label: edgeDraft.label,
        };
        setDraft((current) => ({
            ...current,
            definition: {
                ...(current.definition || { nodes: [], edges: [] }),
                nodes: (current.definition?.nodes as WorkflowNode[]) || [],
                edges: [...(((current.definition?.edges as WorkflowEdge[]) || [])), edge],
            },
        }));
    };

    const updateSelectedNode = (patch: Partial<WorkflowNode>) => {
        if (!selectedNodeKey) return;
        setDraft((current) => ({
            ...current,
            definition: {
                ...(current.definition || { nodes: [], edges: [] }),
                nodes: (((current.definition?.nodes as WorkflowNode[]) || []).map((node) =>
                    node.key === selectedNodeKey ? { ...node, ...patch } : node
                )),
                edges: (current.definition?.edges as WorkflowEdge[]) || [],
            },
        }));
    };

    const runWorkflow = async () => {
        const workflowId = selectedWorkflowId || await saveWorkflow();
        if (!workflowId) return;
        setRunLoading(true);
        try {
            const created = await workflowApi.run(agentId, workflowId);
            setActiveRunId(created.id);
            const nextRuns = await workflowApi.runs(agentId, workflowId);
            setRuns(nextRuns);
            setActiveRunId(nextRuns[0]?.id || created.id);
        } finally {
            setRunLoading(false);
        }
    };

    const resolveApproval = async (action: 'approve' | 'reject') => {
        if (!selectedWorkflowId || !activeRunId) return;
        setApprovalLoading(action);
        try {
            const resolved = await workflowApi.resolveApproval(agentId, selectedWorkflowId, activeRunId, action);
            setRuns((current) => {
                const exists = current.some((item) => item.id === resolved.id);
                if (!exists) return [resolved, ...current];
                return current.map((item) => (item.id === resolved.id ? resolved : item));
            });
            setActiveRunId(resolved.id);
            const fresh = await workflowApi.getRun(agentId, selectedWorkflowId, resolved.id);
            setRuns((current) => current.map((item) => (item.id === fresh.id ? fresh : item)));
        } finally {
            setApprovalLoading(null);
        }
    };

    useEffect(() => {
        if (!selectedWorkflowId || !activeRunId) return;
        const timer = window.setInterval(async () => {
            const run = await workflowApi.getRun(agentId, selectedWorkflowId, activeRunId);
            setRuns((current) => current.map((item) => (item.id === run.id ? run : item)));
        }, 1500);
        return () => window.clearInterval(timer);
    }, [agentId, selectedWorkflowId, activeRunId]);

    const edgeLines = edges.map((edge) => {
        const source = nodes.find((node) => node.key === edge.source);
        const target = nodes.find((node) => node.key === edge.target);
        if (!source || !target) return null;
        const x1 = source.x + 72;
        const y1 = source.y + 28;
        const x2 = target.x + 72;
        const y2 = target.y + 28;
        const midX = (x1 + x2) / 2;
        const path = `M ${x1} ${y1} C ${midX} ${y1}, ${midX} ${y2}, ${x2} ${y2}`;
        return (
            <g key={edge.id}>
                <path d={path} stroke="rgba(148,163,184,0.85)" strokeWidth="2" fill="none" />
                {edge.label ? (
                    <text x={midX} y={(y1 + y2) / 2 - 6} fill="var(--text-tertiary)" fontSize="11" textAnchor="middle">
                        {edge.label}
                    </text>
                ) : null}
            </g>
        );
    });

    return (
        <div style={{ padding: '20px 24px', display: 'grid', gridTemplateColumns: '280px minmax(0, 1fr) 320px', gap: '16px', minHeight: 'calc(100vh - 40px)' }}>
            <div className="card" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                    <div>
                        <div style={{ fontSize: '18px', fontWeight: 600 }}>Workflows</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>{agent?.name || 'Agent'}</div>
                    </div>
                    <button className="btn btn-secondary" onClick={() => navigate(`/agents/${agentId}/chat`)}>
                        <IconArrowLeft size={14} stroke={1.8} />
                    </button>
                </div>
                <button className="btn btn-primary" onClick={createWorkflow}>
                    <IconPlus size={14} stroke={1.8} /> New Workflow
                </button>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', overflowY: 'auto' }}>
                    {workflows.map((item) => (
                        <button
                            key={item.id}
                            className={`btn ${item.id === selectedWorkflowId ? 'btn-primary' : 'btn-secondary'}`}
                            style={{ justifyContent: 'flex-start' }}
                            onClick={() => setSelectedWorkflowId(item.id)}
                        >
                            <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                                <span>{item.name}</span>
                                <span style={{ fontSize: '11px', opacity: 0.75 }}>{item.status} / v{item.version}</span>
                            </span>
                        </button>
                    ))}
                    {!workflows.length ? (
                        <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>No workflows yet. Start with a draft on the right.</div>
                    ) : null}
                </div>
                <div style={{ marginTop: 'auto', display: 'flex', gap: '8px' }}>
                    <button className="btn btn-primary" disabled={saveLoading} onClick={() => void saveWorkflow()}>
                        <IconDeviceFloppy size={14} stroke={1.8} /> {saveLoading ? 'Saving...' : 'Save'}
                    </button>
                    <button className="btn btn-danger" disabled={!selectedWorkflowId} onClick={() => void removeWorkflow()}>
                        <IconTrash size={14} stroke={1.8} /> Delete
                    </button>
                </div>
            </div>

            <div className="card" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 0 }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <input
                        className="form-input"
                        value={draft.name || ''}
                        onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))}
                        placeholder="Workflow name"
                        style={{ minWidth: '240px', flex: '1 1 260px' }}
                    />
                    <select
                        className="form-input"
                        value={draft.status || 'draft'}
                        onChange={(event) => setDraft((current) => ({ ...current, status: event.target.value as any }))}
                        style={{ width: '140px' }}
                    >
                        <option value="draft">draft</option>
                        <option value="active">active</option>
                        <option value="archived">archived</option>
                    </select>
                    <button className="btn btn-primary" onClick={() => void runWorkflow()} disabled={runLoading}>
                        <IconPlayerPlay size={14} stroke={1.8} /> {runLoading ? 'Running...' : 'Run'}
                    </button>
                </div>
                <textarea
                    className="form-input"
                    value={draft.description || ''}
                    onChange={(event) => setDraft((current) => ({ ...current, description: event.target.value }))}
                    placeholder="Workflow description"
                    rows={2}
                />
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
                    <button className="btn btn-secondary" onClick={addNode}>
                        <IconPlus size={14} stroke={1.8} /> Add Node
                    </button>
                    <select
                        className="form-input"
                        value={edgeDraft.source}
                        onChange={(event) => setEdgeDraft((current) => ({ ...current, source: event.target.value }))}
                        style={{ width: '150px' }}
                    >
                        {nodes.map((node) => <option key={`src-${node.key}`} value={node.key}>{node.title}</option>)}
                    </select>
                    <select
                        className="form-input"
                        value={edgeDraft.target}
                        onChange={(event) => setEdgeDraft((current) => ({ ...current, target: event.target.value }))}
                        style={{ width: '150px' }}
                    >
                        {nodes.map((node) => <option key={`tgt-${node.key}`} value={node.key}>{node.title}</option>)}
                    </select>
                    <input
                        className="form-input"
                        value={edgeDraft.label}
                        onChange={(event) => setEdgeDraft((current) => ({ ...current, label: event.target.value }))}
                        placeholder="edge label"
                        style={{ width: '140px' }}
                    />
                    <button className="btn btn-secondary" onClick={addEdge}>Add Edge</button>
                </div>
                <div
                    ref={boardRef}
                    style={{
                        position: 'relative',
                        minHeight: '560px',
                        borderRadius: '10px',
                        border: '1px solid var(--border-subtle)',
                        background:
                            'linear-gradient(to right, rgba(148,163,184,0.08) 1px, transparent 1px), linear-gradient(to bottom, rgba(148,163,184,0.08) 1px, transparent 1px)',
                        backgroundSize: '24px 24px',
                        overflow: 'hidden',
                    }}
                >
                    <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                        {edgeLines}
                    </svg>
                    {nodes.map((node) => {
                        const selected = node.key === selectedNodeKey;
                        return (
                            <button
                                key={node.key}
                                type="button"
                                onClick={() => setSelectedNodeKey(node.key)}
                                onPointerDown={(event) => {
                                    const rect = (event.currentTarget as HTMLButtonElement).getBoundingClientRect();
                                    dragRef.current = {
                                        key: node.key,
                                        offsetX: event.clientX - rect.left,
                                        offsetY: event.clientY - rect.top,
                                    };
                                }}
                                style={{
                                    position: 'absolute',
                                    left: `${node.x}px`,
                                    top: `${node.y}px`,
                                    width: '144px',
                                    minHeight: '58px',
                                    borderRadius: '10px',
                                    border: selected ? '2px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                                    background: selected ? 'var(--accent-subtle)' : 'var(--bg-elevated)',
                                    color: 'var(--text-primary)',
                                    boxShadow: '0 8px 24px rgba(15,23,42,0.14)',
                                    cursor: 'grab',
                                    padding: '10px 12px',
                                    textAlign: 'left',
                                }}
                            >
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>{node.type}</div>
                                <div style={{ fontSize: '13px', fontWeight: 600 }}>{node.title}</div>
                            </button>
                        );
                    })}
                </div>
            </div>

            <div className="card" style={{ padding: '14px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div>
                    <div style={{ fontSize: '16px', fontWeight: 600 }}>Inspector</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>Edit node properties and inspect runs.</div>
                </div>

                {selectedNode ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        <input
                            className="form-input"
                            value={selectedNode.title}
                            onChange={(event) => updateSelectedNode({ title: event.target.value })}
                            placeholder="Node title"
                        />
                        <select
                            className="form-input"
                            value={selectedNode.type}
                            onChange={(event) => updateSelectedNode({ type: event.target.value })}
                        >
                            {NODE_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                        </select>
                        <textarea
                            className="form-input"
                            rows={6}
                            value={JSON.stringify(selectedNode.config || {}, null, 2)}
                            onChange={(event) => {
                                try {
                                    updateSelectedNode({ config: JSON.parse(event.target.value || '{}') });
                                } catch {
                                    // Keep the last valid config until JSON is valid again.
                                }
                            }}
                        />
                        <button className="btn btn-danger" onClick={removeNode}>
                            <IconTrash size={14} stroke={1.8} /> Remove Node
                        </button>
                    </div>
                ) : (
                    <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>Select a node on the canvas.</div>
                )}

                <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '14px' }}>
                    <div style={{ fontSize: '15px', fontWeight: 600, marginBottom: '10px' }}>Runs</div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                        {runs.map((run) => (
                            <button
                                key={run.id}
                                className={`btn ${run.id === activeRunId ? 'btn-primary' : 'btn-secondary'}`}
                                style={{ justifyContent: 'flex-start' }}
                                onClick={async () => {
                                    setActiveRunId(run.id);
                                    if (selectedWorkflowId) {
                                        const fresh = await workflowApi.getRun(agentId, selectedWorkflowId, run.id);
                                        setRuns((current) => current.map((item) => (item.id === fresh.id ? fresh : item)));
                                    }
                                }}
                            >
                                <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start' }}>
                                    <span>{run.status}</span>
                                    <span style={{ fontSize: '11px', opacity: 0.75 }}>{new Date(run.created_at).toLocaleString()}</span>
                                </span>
                            </button>
                        ))}
                        {!runs.length ? (
                            <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>No runs yet.</div>
                        ) : null}
                    </div>
                    {activeRun ? (
                        <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                Current: <strong>{activeRun.current_node_key || 'done'}</strong>
                            </div>
                            {activeRun.status === 'waiting_human' ? (
                                <div
                                    style={{
                                        padding: '10px 12px',
                                        borderRadius: '8px',
                                        border: '1px solid rgba(34,197,94,0.22)',
                                        background: 'rgba(240,253,244,0.95)',
                                        display: 'flex',
                                        flexDirection: 'column',
                                        gap: '8px',
                                    }}
                                >
                                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                        This run is waiting for manual approval before it continues.
                                    </div>
                                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                                        <button
                                            className="btn btn-primary"
                                            disabled={approvalLoading !== null}
                                            onClick={() => void resolveApproval('approve')}
                                        >
                                            {approvalLoading === 'approve' ? 'Approving...' : 'Approve'}
                                        </button>
                                        <button
                                            className="btn btn-danger"
                                            disabled={approvalLoading !== null}
                                            onClick={() => void resolveApproval('reject')}
                                        >
                                            {approvalLoading === 'reject' ? 'Rejecting...' : 'Reject'}
                                        </button>
                                    </div>
                                </div>
                            ) : null}
                            <div style={{ fontSize: '12px', color: activeRun.error_message ? 'var(--error)' : 'var(--text-tertiary)' }}>
                                {activeRun.error_message || 'Run is healthy.'}
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '220px', overflowY: 'auto' }}>
                                {(activeRun.node_runs || []).map((nodeRun) => (
                                    <div
                                        key={nodeRun.id}
                                        style={{
                                            padding: '8px 10px',
                                            borderRadius: '8px',
                                            border: '1px solid var(--border-subtle)',
                                            background: 'var(--bg-secondary)',
                                        }}
                                    >
                                        <div style={{ fontSize: '12px', fontWeight: 600 }}>{nodeRun.title}</div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                            {nodeRun.node_type} / {nodeRun.status}
                                        </div>
                                        {nodeRun.output_payload?.message ? (
                                            <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', lineHeight: 1.5 }}>
                                                {String(nodeRun.output_payload.message)}
                                            </div>
                                        ) : null}
                                        {nodeRun.output_payload?.action ? (
                                            <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginTop: '4px' }}>
                                                Action: {String(nodeRun.output_payload.action)}
                                            </div>
                                        ) : null}
                                    </div>
                                ))}
                            </div>
                        </div>
                    ) : null}
                </div>
            </div>
        </div>
    );
}

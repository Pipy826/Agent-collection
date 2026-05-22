/**
 * Workflow Run Monitor — real-time visualization of workflow execution.
 * Shows node-level status, timing, errors, and allows retry/approval actions.
 */
import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { workflowApi } from '../services/api';

const STATUS_COLORS: Record<string, string> = {
    pending: 'var(--text-tertiary)',
    running: 'var(--warning)',
    completed: 'var(--success)',
    failed: 'var(--error)',
    waiting_human: 'var(--accent-primary)',
    cancelled: 'var(--text-tertiary)',
};

const STATUS_LABELS: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    completed: '已完成',
    failed: '失败',
    waiting_human: '等待审批',
    cancelled: '已取消',
};

const NODE_ICONS: Record<string, string> = {
    start: '▶',
    end: '■',
    task: '📋',
    agent: '🤖',
    tool: '🔧',
    condition: '◇',
    parallel: '⫘',
    approval: '✋',
    human_input: '👤',
    subflow: '🔄',
};

export default function WorkflowRunMonitor() {
    const { id: agentId = '', workflowId = '', runId = '' } = useParams();
    const navigate = useNavigate();
    const qc = useQueryClient();
    const [selectedNode, setSelectedNode] = useState<string | null>(null);

    const { data: run, isLoading } = useQuery({
        queryKey: ['workflow-run', agentId, workflowId, runId],
        queryFn: () => workflowApi.getRun(agentId, workflowId, runId),
        refetchInterval: (query) => {
            const d = query.state.data;
            if (!d) return 3000;
            return ['running', 'pending', 'waiting_human'].includes(d.status) ? 2000 : false;
        },
    });

    const approveMutation = useMutation({
        mutationFn: (action: 'approve' | 'reject') => workflowApi.resolveApproval(agentId, workflowId, runId, action),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['workflow-run', agentId, workflowId, runId] }),
    });

    const cancelMutation = useMutation({
        mutationFn: () => workflowApi.cancelRun(agentId, workflowId, runId),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['workflow-run', agentId, workflowId, runId] }),
    });

    if (isLoading) {
        return (
            <div className="page-container" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh' }}>
                <span style={{ color: 'var(--text-tertiary)', fontSize: '14px' }}>加载中...</span>
            </div>
        );
    }

    if (!run) {
        return (
            <div className="page-container">
                <div className="empty-state">
                    <h3 className="empty-state__title">运行记录未找到</h3>
                </div>
            </div>
        );
    }

    const nodeRuns: any[] = run.node_runs || [];
    const nodes: any[] = (run as any).definition?.nodes || nodeRuns.map((nr: any) => ({ key: nr.node_key, type: nr.node_type, title: nr.title }));
    const selectedNodeRun = nodeRuns.find((nr: any) => nr.node_key === selectedNode);

    const elapsed = run.started_at && run.finished_at
        ? Math.round((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)
        : run.started_at
            ? Math.round((Date.now() - new Date(run.started_at).getTime()) / 1000)
            : 0;

    return (
        <div className="page-container page-container--wide">
            {/* Header */}
            <div className="page-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <button className="btn btn-ghost" onClick={() => navigate(-1)} style={{ padding: '4px 8px' }}>
                        ← 返回
                    </button>
                    <div>
                        <h1 className="page-header__title" style={{ fontSize: '18px' }}>工作流运行监控</h1>
                        <p className="page-header__subtitle">实时查看节点执行状态</p>
                    </div>
                </div>
                <div className="page-header__actions">
                    {run.status === 'waiting_human' && (
                        <>
                            <button className="btn btn-primary" onClick={() => approveMutation.mutate('approve')} disabled={approveMutation.isPending}>通过</button>
                            <button className="btn btn-danger" onClick={() => approveMutation.mutate('reject')} disabled={approveMutation.isPending}>拒绝</button>
                        </>
                    )}
                    {['running', 'pending'].includes(run.status) && (
                        <button className="btn btn-secondary" onClick={() => cancelMutation.mutate()} disabled={cancelMutation.isPending}>取消运行</button>
                    )}
                </div>
            </div>

            {/* Run Summary */}
            <div className="stat-grid" style={{ marginBottom: '24px' }}>
                <div className="stat-card">
                    <span className="stat-card__label">状态</span>
                    <span className="stat-card__value" style={{ color: STATUS_COLORS[run.status], fontSize: '16px' }}>
                        {STATUS_LABELS[run.status] || run.status}
                    </span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">耗时</span>
                    <span className="stat-card__value" style={{ fontSize: '16px' }}>{elapsed}s</span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">节点数</span>
                    <span className="stat-card__value" style={{ fontSize: '16px' }}>{nodes.length}</span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">当前节点</span>
                    <span className="stat-card__value" style={{ fontSize: '14px' }}>{run.current_node_key || '—'}</span>
                </div>
            </div>

            {/* Node Timeline */}
            <div style={{ display: 'flex', gap: '20px' }}>
                {/* Left: Node list */}
                <div style={{ flex: 1, minWidth: 0 }}>
                    <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>节点执行流</h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                        {nodes.map((node: any, idx: number) => {
                            const nodeRun = nodeRuns.find((nr: any) => nr.node_key === node.key);
                            const status = nodeRun?.status || 'pending';
                            const isCurrent = run.current_node_key === node.key;
                            return (
                                <div
                                    key={node.key}
                                    onClick={() => setSelectedNode(node.key)}
                                    style={{
                                        display: 'flex', alignItems: 'center', gap: '10px',
                                        padding: '10px 12px', borderRadius: 'var(--radius-lg)',
                                        background: selectedNode === node.key ? 'var(--accent-subtle)' : isCurrent ? 'var(--bg-hover)' : 'var(--bg-secondary)',
                                        border: `1px solid ${selectedNode === node.key ? 'var(--accent-primary)' : 'var(--border-subtle)'}`,
                                        cursor: 'pointer', transition: 'all 0.12s',
                                    }}
                                >
                                    {/* Status indicator */}
                                    <div style={{
                                        width: '8px', height: '8px', borderRadius: '50%', flexShrink: 0,
                                        background: STATUS_COLORS[status],
                                        boxShadow: status === 'running' ? `0 0 6px ${STATUS_COLORS[status]}` : undefined,
                                        animation: status === 'running' ? 'pulse 1.5s infinite' : undefined,
                                    }} />

                                    {/* Node icon */}
                                    <span style={{ fontSize: '14px', flexShrink: 0 }}>{NODE_ICONS[node.type] || '●'}</span>

                                    {/* Node info */}
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontSize: '13px', fontWeight: 500, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {node.title || node.key}
                                        </div>
                                        <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                            {node.type} · {STATUS_LABELS[status] || status}
                                        </div>
                                    </div>

                                    {/* Duration */}
                                    {nodeRun?.started_at && (
                                        <span style={{ fontSize: '11px', color: 'var(--text-tertiary)', flexShrink: 0 }}>
                                            {nodeRun.finished_at
                                                ? `${Math.round((new Date(nodeRun.finished_at).getTime() - new Date(nodeRun.started_at).getTime()) / 1000)}s`
                                                : '...'
                                            }
                                        </span>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>

                {/* Right: Node detail panel */}
                <div style={{ width: '340px', flexShrink: 0 }}>
                    <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>节点详情</h3>
                    {!selectedNode ? (
                        <div style={{ padding: '40px 20px', textAlign: 'center', color: 'var(--text-tertiary)', fontSize: '13px' }}>
                            点击左侧节点查看详情
                        </div>
                    ) : (
                        <div className="card" style={{ padding: '16px' }}>
                            <div style={{ marginBottom: '12px' }}>
                                <div style={{ fontSize: '14px', fontWeight: 600, marginBottom: '4px' }}>
                                    {nodes.find((n: any) => n.key === selectedNode)?.title || selectedNode}
                                </div>
                                <span className={`badge badge--${selectedNodeRun?.status === 'completed' ? 'success' : selectedNodeRun?.status === 'failed' ? 'error' : 'default'}`}>
                                    {STATUS_LABELS[selectedNodeRun?.status] || selectedNodeRun?.status || '未执行'}
                                </span>
                            </div>

                            {selectedNodeRun?.error_message && (
                                <div style={{ padding: '8px 10px', borderRadius: '6px', background: 'var(--error-subtle)', color: 'var(--error)', fontSize: '12px', marginBottom: '12px', lineHeight: 1.5 }}>
                                    {selectedNodeRun.error_message}
                                </div>
                            )}

                            {selectedNodeRun?.input_payload && Object.keys(selectedNodeRun.input_payload).length > 0 && (
                                <div style={{ marginBottom: '12px' }}>
                                    <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)', marginBottom: '4px', textTransform: 'uppercase' }}>输入</div>
                                    <pre style={{ fontSize: '11px', color: 'var(--text-secondary)', background: 'var(--bg-hover)', padding: '8px', borderRadius: '6px', overflow: 'auto', maxHeight: '120px', margin: 0 }}>
                                        {JSON.stringify(selectedNodeRun.input_payload, null, 2)}
                                    </pre>
                                </div>
                            )}

                            {selectedNodeRun?.output_payload && Object.keys(selectedNodeRun.output_payload).length > 0 && (
                                <div style={{ marginBottom: '12px' }}>
                                    <div style={{ fontSize: '11px', fontWeight: 600, color: 'var(--text-tertiary)', marginBottom: '4px', textTransform: 'uppercase' }}>输出</div>
                                    <pre style={{ fontSize: '11px', color: 'var(--text-secondary)', background: 'var(--bg-hover)', padding: '8px', borderRadius: '6px', overflow: 'auto', maxHeight: '120px', margin: 0 }}>
                                        {JSON.stringify(selectedNodeRun.output_payload, null, 2)}
                                    </pre>
                                </div>
                            )}

                            {selectedNodeRun?.started_at && (
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', lineHeight: 1.8 }}>
                                    <div>开始: {new Date(selectedNodeRun.started_at).toLocaleString()}</div>
                                    {selectedNodeRun.finished_at && <div>结束: {new Date(selectedNodeRun.finished_at).toLocaleString()}</div>}
                                    <div>尝试次数: {selectedNodeRun.attempt || 1}</div>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* Error message */}
            {run.error_message && (
                <div style={{ marginTop: '20px', padding: '12px 16px', borderRadius: 'var(--radius-lg)', background: 'var(--error-subtle)', border: '1px solid var(--error)', color: 'var(--error)', fontSize: '13px' }}>
                    <strong>运行错误：</strong>{run.error_message}
                </div>
            )}
        </div>
    );
}

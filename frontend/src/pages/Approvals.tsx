import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { approvalApi } from '../services/api';

export default function Approvals() {
    const qc = useQueryClient();
    const [tab, setTab] = useState<'pending' | 'approved' | 'rejected'>('pending');
    const [resolveNote, setResolveNote] = useState('');
    const [resolvingId, setResolvingId] = useState<string | null>(null);

    const { data: approvals = [], isLoading } = useQuery({ queryKey: ['approvals', tab], queryFn: () => approvalApi.list(tab) });
    const { data: stats } = useQuery({ queryKey: ['approval-stats'], queryFn: approvalApi.stats });

    const resolveMutation = useMutation({
        mutationFn: ({ id, action }: { id: string; action: 'approve' | 'reject' }) =>
            approvalApi.resolve(id, action, resolveNote || undefined),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ['approvals'] }); qc.invalidateQueries({ queryKey: ['approval-stats'] }); setResolvingId(null); setResolveNote(''); },
    });

    const riskColors: Record<string, string> = { low: 'default', medium: 'warning', high: 'error', critical: 'error' };

    return (
        <div className="page-container">
            <div className="page-header">
                <div>
                    <h1 className="page-header__title">审批中心</h1>
                    <p className="page-header__subtitle">管理 Agent 危险操作的审批请求</p>
                </div>
            </div>

            {/* Stats */}
            <div className="stat-grid" style={{ marginBottom: '24px' }}>
                <div className="stat-card">
                    <span className="stat-card__label">待审批</span>
                    <span className="stat-card__value" style={{ color: stats?.pending ? 'var(--warning)' : undefined }}>{stats?.pending ?? 0}</span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">已通过</span>
                    <span className="stat-card__value">{stats?.approved ?? 0}</span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">已拒绝</span>
                    <span className="stat-card__value">{stats?.rejected ?? 0}</span>
                </div>
            </div>

            <div className="tabs">
                <button className={`tabs__item ${tab === 'pending' ? 'tabs__item--active' : ''}`} onClick={() => setTab('pending')}>
                    待审批 {stats?.pending ? `(${stats.pending})` : ''}
                </button>
                <button className={`tabs__item ${tab === 'approved' ? 'tabs__item--active' : ''}`} onClick={() => setTab('approved')}>已通过</button>
                <button className={`tabs__item ${tab === 'rejected' ? 'tabs__item--active' : ''}`} onClick={() => setTab('rejected')}>已拒绝</button>
            </div>

            {isLoading && <p style={{ color: 'var(--text-tertiary)', fontSize: '13px' }}>加载中...</p>}

            {!isLoading && approvals.length === 0 && (
                <div className="empty-state">
                    <h3 className="empty-state__title">{tab === 'pending' ? '没有待审批的请求' : '暂无记录'}</h3>
                    <p className="empty-state__description">{tab === 'pending' ? 'Agent 的危险操作会在这里等待你的审批' : ''}</p>
                </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                {approvals.map((a: any) => (
                    <div key={a.id} className="card" style={{ padding: '16px 20px' }}>
                        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px' }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                                    <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-primary)' }}>{a.agent_name}</span>
                                    <span className={`badge badge--${riskColors[a.risk_level] || 'default'}`}>{a.risk_level}</span>
                                    <span className="badge badge--default">{a.action_type}</span>
                                </div>
                                <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '6px', lineHeight: 1.5 }}>{a.action_description}</p>
                                <div style={{ fontSize: '11px', color: 'var(--text-tertiary)' }}>
                                    {new Date(a.created_at).toLocaleString()}
                                    {a.resolved_at && ` · 处理于 ${new Date(a.resolved_at).toLocaleString()}`}
                                </div>
                            </div>

                            {tab === 'pending' && (
                                <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                                    {resolvingId === a.id ? (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                            <input
                                                style={{ fontSize: '12px', padding: '4px 8px', width: '180px' }}
                                                placeholder="备注（可选）"
                                                value={resolveNote}
                                                onChange={e => setResolveNote(e.target.value)}
                                            />
                                            <div style={{ display: 'flex', gap: '6px' }}>
                                                <button className="btn btn-primary" style={{ fontSize: '11px', padding: '3px 8px' }}
                                                    onClick={() => resolveMutation.mutate({ id: a.id, action: 'approve' })}>通过</button>
                                                <button className="btn btn-danger" style={{ fontSize: '11px', padding: '3px 8px' }}
                                                    onClick={() => resolveMutation.mutate({ id: a.id, action: 'reject' })}>拒绝</button>
                                                <button className="btn btn-ghost" style={{ fontSize: '11px', padding: '3px 8px' }}
                                                    onClick={() => setResolvingId(null)}>取消</button>
                                            </div>
                                        </div>
                                    ) : (
                                        <button className="btn btn-secondary" onClick={() => setResolvingId(a.id)}>处理</button>
                                    )}
                                </div>
                            )}

                            {tab !== 'pending' && (
                                <span className={`badge badge--${a.status === 'approved' ? 'success' : 'error'}`}>
                                    {a.status === 'approved' ? '已通过' : '已拒绝'}
                                </span>
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { a2aApi } from '../services/api';

export default function A2AManagement() {
    const { t } = useTranslation();
    const qc = useQueryClient();
    const [tab, setTab] = useState<'instances' | 'discover' | 'audit'>('instances');
    const [showAdd, setShowAdd] = useState(false);
    const [form, setForm] = useState({ name: '', base_url: '', auth_type: 'api_key', auth_credential: '' });
    const [searchQuery, setSearchQuery] = useState('');

    const { data: instances = [], isLoading } = useQuery({ queryKey: ['a2a-instances'], queryFn: a2aApi.listInstances });
    const { data: auditLogs = [] } = useQuery({ queryKey: ['a2a-audit'], queryFn: () => a2aApi.getAuditLogs(50), enabled: tab === 'audit' });
    const { data: searchResults = [], refetch: doSearch } = useQuery({
        queryKey: ['a2a-search', searchQuery],
        queryFn: () => a2aApi.searchAgents({ query: searchQuery || undefined, limit: 20 }),
        enabled: false,
    });

    const addMutation = useMutation({
        mutationFn: () => a2aApi.createInstance(form),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ['a2a-instances'] }); setShowAdd(false); setForm({ name: '', base_url: '', auth_type: 'api_key', auth_credential: '' }); },
    });

    const syncMutation = useMutation({
        mutationFn: (id: string) => a2aApi.syncInstance(id),
        onSuccess: () => qc.invalidateQueries({ queryKey: ['a2a-instances'] }),
    });

    return (
        <div className="page-container">
            <div className="page-header">
                <div>
                    <h1 className="page-header__title">A2A 跨实例协作</h1>
                    <p className="page-header__subtitle">管理远端实例、发现远程 Agent、查看跨实例任务审计</p>
                </div>
                <div className="page-header__actions">
                    {tab === 'instances' && (
                        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>+ 注册实例</button>
                    )}
                </div>
            </div>

            <div className="tabs">
                <button className={`tabs__item ${tab === 'instances' ? 'tabs__item--active' : ''}`} onClick={() => setTab('instances')}>远端实例</button>
                <button className={`tabs__item ${tab === 'discover' ? 'tabs__item--active' : ''}`} onClick={() => setTab('discover')}>Agent 发现</button>
                <button className={`tabs__item ${tab === 'audit' ? 'tabs__item--active' : ''}`} onClick={() => setTab('audit')}>审计日志</button>
            </div>

            {tab === 'instances' && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {isLoading && <p style={{ color: 'var(--text-tertiary)', fontSize: '13px' }}>加载中...</p>}
                    {!isLoading && instances.length === 0 && (
                        <div className="empty-state">
                            <h3 className="empty-state__title">暂无远端实例</h3>
                            <p className="empty-state__description">注册一个远端 Clawith 实例，开始跨实例 Agent 协作</p>
                        </div>
                    )}
                    {instances.map((inst: any) => (
                        <div key={inst.id} className="card" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
                            <div style={{ flex: 1, minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                                    <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-primary)' }}>{inst.name}</span>
                                    <span className={`badge badge--${inst.status === 'active' ? 'success' : inst.status === 'unreachable' ? 'error' : 'default'}`}>{inst.status}</span>
                                </div>
                                <div style={{ fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                    {inst.base_url} · {inst.agent_count} agents · v{inst.protocol_version}
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '8px' }}>
                                <button className="btn btn-secondary" onClick={() => syncMutation.mutate(inst.id)} disabled={syncMutation.isPending}>
                                    {syncMutation.isPending ? '同步中...' : '同步'}
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {tab === 'discover' && (
                <div>
                    <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
                        <input
                            style={{ flex: 1, padding: '8px 12px', fontSize: '13px' }}
                            placeholder="搜索远端 Agent（技能、标签或名称）"
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                            onKeyDown={e => e.key === 'Enter' && doSearch()}
                        />
                        <button className="btn btn-primary" onClick={() => doSearch()}>搜索</button>
                    </div>
                    {searchResults.length === 0 && (
                        <div className="empty-state">
                            <h3 className="empty-state__title">搜索远端 Agent</h3>
                            <p className="empty-state__description">输入技能或关键词，发现其他实例上的可用 Agent</p>
                        </div>
                    )}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        {searchResults.map((card: any) => (
                            <div key={card.id} className="card card--interactive">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                                    <span style={{ fontWeight: 600, fontSize: '14px' }}>{card.name}</span>
                                    <span className="badge badge--accent">{card.instance_name}</span>
                                    <span className={`status-dot status-dot--${card.availability_status === 'available' ? 'active' : 'idle'}`} />
                                </div>
                                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '8px' }}>{card.description}</p>
                                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                                    {(card.skills || []).map((s: string) => <span key={s} className="badge badge--default">{s}</span>)}
                                    {(card.labels || []).map((l: string) => <span key={l} className="badge badge--accent">{l}</span>)}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {tab === 'audit' && (
                <div>
                    {auditLogs.length === 0 && <p style={{ color: 'var(--text-tertiary)', fontSize: '13px', textAlign: 'center', padding: '40px' }}>暂无审计记录</p>}
                    <table className="data-table">
                        <thead><tr><th>时间</th><th>事件</th><th>方向</th><th>详情</th></tr></thead>
                        <tbody>
                            {auditLogs.map((log: any) => (
                                <tr key={log.id}>
                                    <td style={{ whiteSpace: 'nowrap' }}>{new Date(log.created_at).toLocaleString()}</td>
                                    <td><span className="badge badge--default">{log.event_type}</span></td>
                                    <td>{log.direction === 'outbound' ? '→ 出站' : '← 入站'}</td>
                                    <td style={{ fontSize: '11px', color: 'var(--text-tertiary)', maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{JSON.stringify(log.payload)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Add Instance Modal */}
            {showAdd && (
                <div className="modal-backdrop" onClick={e => { if (e.target === e.currentTarget) setShowAdd(false); }}>
                    <div className="modal-content">
                        <div className="modal-header">
                            <h3 className="modal-header__title">注册远端实例</h3>
                            <button className="modal-header__close" onClick={() => setShowAdd(false)}>✕</button>
                        </div>
                        <div className="form-group">
                            <label className="form-group__label">实例名称</label>
                            <input value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))} placeholder="例如：上海分部" />
                        </div>
                        <div className="form-group">
                            <label className="form-group__label">Base URL</label>
                            <input value={form.base_url} onChange={e => setForm(f => ({ ...f, base_url: e.target.value }))} placeholder="https://remote.example.com" />
                        </div>
                        <div className="form-group">
                            <label className="form-group__label">API Key（可选）</label>
                            <input value={form.auth_credential} onChange={e => setForm(f => ({ ...f, auth_credential: e.target.value }))} placeholder="远端实例的 API Key" />
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowAdd(false)}>取消</button>
                            <button className="btn btn-primary" onClick={() => addMutation.mutate()} disabled={!form.name || !form.base_url || addMutation.isPending}>
                                {addMutation.isPending ? '注册中...' : '注册'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

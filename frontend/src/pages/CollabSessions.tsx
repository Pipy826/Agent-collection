import { useState, useRef, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { collabApi, agentApi } from '../services/api';
import { useAuthStore } from '../stores';

export default function CollabSessions() {
    const qc = useQueryClient();
    const user = useAuthStore(s => s.user);
    const [activeSession, setActiveSession] = useState<string | null>(null);
    const [showCreate, setShowCreate] = useState(false);
    const [createForm, setCreateForm] = useState({ title: '', agent_ids: [] as string[] });
    const [msgInput, setMsgInput] = useState('');
    const messagesEndRef = useRef<HTMLDivElement>(null);

    const { data: sessions = [] } = useQuery({ queryKey: ['collab-sessions'], queryFn: collabApi.listSessions });
    const { data: agents = [] } = useQuery({ queryKey: ['agents-list'], queryFn: () => agentApi.list() });
    const { data: messages = [], refetch: refetchMessages } = useQuery({
        queryKey: ['collab-messages', activeSession],
        queryFn: () => collabApi.getMessages(activeSession!, 100),
        enabled: !!activeSession,
        refetchInterval: 3000,
    });
    const { data: participants = [] } = useQuery({
        queryKey: ['collab-participants', activeSession],
        queryFn: () => collabApi.getParticipants(activeSession!),
        enabled: !!activeSession,
    });

    const createMutation = useMutation({
        mutationFn: () => collabApi.createSession({ title: createForm.title, agent_ids: createForm.agent_ids }),
        onSuccess: (data) => { qc.invalidateQueries({ queryKey: ['collab-sessions'] }); setShowCreate(false); setActiveSession(data.id); setCreateForm({ title: '', agent_ids: [] }); },
    });

    const sendMutation = useMutation({
        mutationFn: () => {
            const mentionedAgents = participants.filter((p: any) => p.participant_type === 'agent' && p.is_active).map((p: any) => p.agent_id);
            return collabApi.sendMessage(activeSession!, { content: msgInput, mentioned_ids: mentionedAgents });
        },
        onSuccess: () => { setMsgInput(''); refetchMessages(); },
    });

    useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

    return (
        <div style={{ display: 'flex', height: '100%', minHeight: 0, padding: '12px', boxSizing: 'border-box' }}>
            <div style={{
                display: 'flex', flex: 1, minHeight: 0,
                background: 'var(--bg-elevated)', border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-xl)', overflow: 'hidden',
                boxShadow: '0 1px 4px rgba(0,0,0,0.04)',
            }}>
            {/* Left panel */}
            <div style={{
                width: '220px', flexShrink: 0, display: 'flex', flexDirection: 'column',
                borderRight: '1px solid var(--border-subtle)',
                padding: '14px 12px', overflow: 'hidden',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                    <span style={{ fontSize: '14px', fontWeight: 700, color: 'var(--text-primary)' }}>我的会话</span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-tertiary)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ cursor: 'pointer' }}>
                        <rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18M15 3v18"/>
                    </svg>
                </div>

                <button
                    onClick={() => setShowCreate(true)}
                    style={{
                        width: '100%', padding: '7px 0', marginBottom: '12px',
                        border: '1px solid var(--border-subtle)', borderRadius: '6px',
                        background: 'transparent', color: 'var(--text-secondary)',
                        fontSize: '13px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px',
                    }}
                >
                    + 新建会话
                </button>

                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '2px' }}>
                    {sessions.length === 0 && (
                        <div style={{ color: 'var(--text-tertiary)', fontSize: '12px', lineHeight: 1.6 }}>
                            还没有会话。<br />点击"新建会话"开始。
                        </div>
                    )}
                    {sessions.map((s: any) => (
                        <div
                            key={s.id}
                            onClick={() => setActiveSession(s.id)}
                            style={{
                                padding: '7px 8px', borderRadius: '6px', cursor: 'pointer',
                                background: activeSession === s.id ? 'var(--bg-hover)' : 'transparent',
                                fontSize: '13px', color: activeSession === s.id ? 'var(--text-primary)' : 'var(--text-secondary)',
                                fontWeight: activeSession === s.id ? 600 : 400,
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                            }}
                        >
                            {s.title}
                        </div>
                    ))}
                </div>
            </div>

            {/* Right — main area */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                {!activeSession ? (
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '12px' }}>
                        <span style={{ fontSize: '14px', color: 'var(--text-tertiary)' }}>未选择会话</span>
                        <button
                            onClick={() => setShowCreate(true)}
                            style={{
                                padding: '7px 16px', fontSize: '13px',
                                border: '1px solid var(--border-default)', borderRadius: '6px',
                                background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer',
                            }}
                        >
                            开始新会话
                        </button>
                    </div>
                ) : (
                    <>
                        {/* Header */}
                        <div style={{
                            padding: '8px 16px', borderBottom: '1px solid var(--border-subtle)',
                            display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
                        }}>
                            <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-primary)' }}>
                                {sessions.find((s: any) => s.id === activeSession)?.title}
                            </div>
                            <div style={{ display: 'flex', gap: '3px' }}>
                                {participants.filter((p: any) => p.is_active).map((p: any) => (
                                    <div key={p.id} title={p.display_name} style={{
                                        width: '22px', height: '22px', borderRadius: '50%',
                                        background: p.participant_type === 'agent' ? 'var(--accent-subtle)' : 'var(--bg-tertiary)',
                                        border: '1px solid var(--border-subtle)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                        fontSize: '9px', fontWeight: 600,
                                        color: p.participant_type === 'agent' ? 'var(--accent-text)' : 'var(--text-secondary)',
                                    }}>
                                        {p.display_name[0]}
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Messages */}
                        <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            {messages.map((msg: any) => {
                                const isMe = msg.sender_type === 'human' && msg.sender_id === user?.id;
                                const isSystem = msg.sender_type === 'system';
                                return (
                                    <div key={msg.id} style={{
                                        display: 'flex', gap: '8px',
                                        flexDirection: isMe ? 'row-reverse' : 'row',
                                        alignItems: 'flex-start',
                                        justifyContent: isSystem ? 'center' : undefined,
                                    }}>
                                        {!isSystem && (
                                            <div style={{
                                                width: '26px', height: '26px', borderRadius: '50%', flexShrink: 0,
                                                background: msg.sender_type === 'agent' ? 'var(--accent-subtle)' : 'var(--bg-tertiary)',
                                                border: '1px solid var(--border-subtle)',
                                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                fontSize: '10px', fontWeight: 600,
                                                color: msg.sender_type === 'agent' ? 'var(--accent-text)' : 'var(--text-secondary)',
                                            }}>
                                                {msg.sender_name[0]}
                                            </div>
                                        )}
                                        <div style={{ maxWidth: isSystem ? '100%' : '68%' }}>
                                            {!isSystem && (
                                                <div style={{ fontSize: '10px', color: 'var(--text-tertiary)', marginBottom: '2px', textAlign: isMe ? 'right' : 'left' }}>
                                                    {msg.sender_name}
                                                </div>
                                            )}
                                            <div style={{
                                                padding: isSystem ? '0' : '7px 11px',
                                                borderRadius: '8px', lineHeight: 1.5,
                                                background: isSystem ? 'transparent' : isMe ? 'var(--accent-primary)' : 'var(--bg-elevated)',
                                                color: isSystem ? 'var(--text-tertiary)' : isMe ? '#fff' : 'var(--text-primary)',
                                                border: isSystem ? 'none' : '1px solid var(--border-subtle)',
                                                fontStyle: isSystem ? 'italic' : 'normal',
                                                fontSize: isSystem ? '11px' : '13px',
                                                textAlign: isSystem ? 'center' : 'left',
                                            }}>
                                                {msg.content}
                                            </div>
                                        </div>
                                    </div>
                                );
                            })}
                            <div ref={messagesEndRef} />
                        </div>

                        {/* Input */}
                        <div style={{ padding: '10px 16px', borderTop: '1px solid var(--border-subtle)', display: 'flex', gap: '8px', flexShrink: 0 }}>
                            <input
                                style={{ flex: 1, padding: '7px 12px', fontSize: '13px' }}
                                placeholder="输入消息..."
                                value={msgInput}
                                onChange={e => setMsgInput(e.target.value)}
                                onKeyDown={e => { if (e.key === 'Enter' && msgInput.trim()) sendMutation.mutate(); }}
                            />
                            <button className="btn btn-primary" style={{ padding: '5px 12px', fontSize: '12px' }} onClick={() => sendMutation.mutate()} disabled={!msgInput.trim() || sendMutation.isPending}>
                                发送
                            </button>
                        </div>
                    </>
                )}
            </div>
            </div>{/* end white card wrapper */}

            {/* Create Modal */}
            {showCreate && (
                <div className="modal-backdrop" onClick={e => { if (e.target === e.currentTarget) setShowCreate(false); }}>
                    <div className="modal-content">
                        <div className="modal-header">
                            <h3 className="modal-header__title">新建协作会话</h3>
                            <button className="modal-header__close" onClick={() => setShowCreate(false)}>✕</button>
                        </div>
                        <div className="form-group">
                            <label className="form-group__label">会话标题</label>
                            <input value={createForm.title} onChange={e => setCreateForm(f => ({ ...f, title: e.target.value }))} placeholder="例如：产品需求讨论" />
                        </div>
                        <div className="form-group">
                            <label className="form-group__label">选择 Agent 参与者</label>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '200px', overflowY: 'auto' }}>
                                {agents.map((agent: any) => (
                                    <label key={agent.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 8px', borderRadius: '6px', cursor: 'pointer', background: createForm.agent_ids.includes(agent.id) ? 'var(--accent-subtle)' : 'transparent', fontSize: '13px' }}>
                                        <input
                                            type="checkbox"
                                            checked={createForm.agent_ids.includes(agent.id)}
                                            onChange={e => {
                                                if (e.target.checked) setCreateForm(f => ({ ...f, agent_ids: [...f.agent_ids, agent.id] }));
                                                else setCreateForm(f => ({ ...f, agent_ids: f.agent_ids.filter(id => id !== agent.id) }));
                                            }}
                                        />
                                        {agent.name}
                                    </label>
                                ))}
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowCreate(false)}>取消</button>
                            <button className="btn btn-primary" onClick={() => createMutation.mutate()} disabled={!createForm.title || createForm.agent_ids.length === 0 || createMutation.isPending}>
                                {createMutation.isPending ? '创建中...' : '创建'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

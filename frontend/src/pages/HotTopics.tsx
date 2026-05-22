import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { hotTopicsApi } from '../services/api';

export default function HotTopics() {
    const [days, setDays] = useState(30);
    const { data, isLoading } = useQuery({ queryKey: ['hot-topics', days], queryFn: () => hotTopicsApi.get(days) });

    const topics = data?.topics || [];
    const summary = data?.summary || {};

    return (
        <div className="page-container">
            <div className="page-header">
                <div>
                    <h1 className="page-header__title">热点分析</h1>
                    <p className="page-header__subtitle">发现团队高频提问与知识库缺口，帮助管理员补充知识</p>
                </div>
                <div className="page-header__actions">
                    <select value={days} onChange={e => setDays(Number(e.target.value))} style={{ fontSize: '13px' }}>
                        <option value={7}>最近 7 天</option>
                        <option value={14}>最近 14 天</option>
                        <option value={30}>最近 30 天</option>
                        <option value={90}>最近 90 天</option>
                    </select>
                </div>
            </div>

            {/* Summary Stats */}
            <div className="stat-grid">
                <div className="stat-card">
                    <span className="stat-card__label">负面反馈总数</span>
                    <span className="stat-card__value">{summary.total_negative_feedback ?? 0}</span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">检测到的话题</span>
                    <span className="stat-card__value">{summary.total_topics_detected ?? 0}</span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">未覆盖话题</span>
                    <span className="stat-card__value" style={{ color: summary.uncovered_topics_count ? 'var(--warning)' : undefined }}>
                        {summary.uncovered_topics_count ?? 0}
                    </span>
                </div>
                <div className="stat-card">
                    <span className="stat-card__label">知识覆盖率</span>
                    <span className="stat-card__value">{summary.coverage_rate ?? 100}%</span>
                    <span className={`stat-card__trend ${(summary.coverage_rate ?? 100) >= 80 ? 'stat-card__trend--up' : 'stat-card__trend--down'}`}>
                        {(summary.coverage_rate ?? 100) >= 80 ? '良好' : '需要补充'}
                    </span>
                </div>
            </div>

            {isLoading && <p style={{ color: 'var(--text-tertiary)', fontSize: '13px' }}>分析中...</p>}

            {!isLoading && topics.length === 0 && (
                <div className="empty-state">
                    <h3 className="empty-state__title">暂无热点话题</h3>
                    <p className="empty-state__description">当 Agent 收到足够多的负面反馈时，系统会自动聚类分析高频问题</p>
                </div>
            )}

            {topics.length > 0 && (
                <div>
                    <h3 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '12px', color: 'var(--text-primary)' }}>
                        知识缺口 Top {topics.length}
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                        {topics.map((topic: any, idx: number) => (
                            <div key={idx} className="card" style={{ padding: '14px 18px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                        <span style={{ fontWeight: 600, fontSize: '14px', color: 'var(--text-primary)' }}>{topic.topic}</span>
                                        {topic.has_golden_example && <span className="badge badge--success">已有答案</span>}
                                        {!topic.has_golden_example && <span className="badge badge--warning">待补充</span>}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '12px', color: 'var(--text-tertiary)' }}>
                                        <span>🔥 {topic.frequency} 次</span>
                                        <span>👎 {topic.negative_feedback_count} 负面</span>
                                    </div>
                                </div>

                                {topic.sample_questions && topic.sample_questions.length > 0 && (
                                    <div style={{ marginTop: '8px' }}>
                                        <div style={{ fontSize: '11px', color: 'var(--text-tertiary)', marginBottom: '4px' }}>示例问题：</div>
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                                            {topic.sample_questions.slice(0, 3).map((q: string, i: number) => (
                                                <div key={i} style={{ fontSize: '12px', color: 'var(--text-secondary)', padding: '3px 8px', background: 'var(--bg-hover)', borderRadius: '4px' }}>
                                                    "{q}"
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--accent-text)' }}>
                                    建议：{topic.suggested_action === 'add_to_kb' ? '添加到企业知识库' : '审查现有答案'}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

/**
 * Unified UI Components — Clawith Design System
 *
 * Provides reusable, consistently-styled components that match the
 * Linear-inspired dark theme defined in index.css.
 *
 * Usage:
 *   import { PageContainer, PageHeader, Card, Badge, StatCard, EmptyState, Tabs } from '@/components/ui';
 */

import { ReactNode, CSSProperties } from 'react';

// ── Page Layout ────────────────────────────────────────

interface PageContainerProps {
    children: ReactNode;
    variant?: 'default' | 'wide' | 'narrow';
    style?: CSSProperties;
}

export function PageContainer({ children, variant = 'default', style }: PageContainerProps) {
    const cls = variant === 'default'
        ? 'page-container'
        : `page-container page-container--${variant}`;
    return <div className={cls} style={style}>{children}</div>;
}

interface PageHeaderProps {
    title: string;
    subtitle?: string;
    actions?: ReactNode;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
    return (
        <div className="page-header">
            <div>
                <h1 className="page-header__title">{title}</h1>
                {subtitle && <p className="page-header__subtitle">{subtitle}</p>}
            </div>
            {actions && <div className="page-header__actions">{actions}</div>}
        </div>
    );
}

// ── Cards ──────────────────────────────────────────────

interface CardProps {
    children: ReactNode;
    interactive?: boolean;
    elevated?: boolean;
    style?: CSSProperties;
    className?: string;
    onClick?: () => void;
}

export function Card({ children, interactive, elevated, style, className, onClick }: CardProps) {
    const cls = [
        'card',
        interactive && 'card--interactive',
        elevated && 'card--elevated',
        className,
    ].filter(Boolean).join(' ');
    return <div className={cls} style={style} onClick={onClick}>{children}</div>;
}

interface CardHeaderProps {
    title: string;
    actions?: ReactNode;
}

export function CardHeader({ title, actions }: CardHeaderProps) {
    return (
        <div className="card__header">
            <span className="card__title">{title}</span>
            {actions}
        </div>
    );
}

// ── Stat Cards ─────────────────────────────────────────

interface StatCardProps {
    label: string;
    value: string | number;
    trend?: string;
    trendDirection?: 'up' | 'down' | 'neutral';
    icon?: ReactNode;
}

export function StatCard({ label, value, trend, trendDirection = 'neutral', icon }: StatCardProps) {
    const trendCls = trendDirection === 'up'
        ? 'stat-card__trend stat-card__trend--up'
        : trendDirection === 'down'
            ? 'stat-card__trend stat-card__trend--down'
            : 'stat-card__trend';

    return (
        <div className="stat-card">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span className="stat-card__label">{label}</span>
                {icon && <span style={{ color: 'var(--text-tertiary)' }}>{icon}</span>}
            </div>
            <span className="stat-card__value">{value}</span>
            {trend && <span className={trendCls}>{trend}</span>}
        </div>
    );
}

export function StatGrid({ children }: { children: ReactNode }) {
    return <div className="stat-grid">{children}</div>;
}

// ── Badges ─────────────────────────────────────────────

interface BadgeProps {
    children: ReactNode;
    variant?: 'default' | 'accent' | 'success' | 'warning' | 'error';
}

export function Badge({ children, variant = 'default' }: BadgeProps) {
    return <span className={`badge badge--${variant}`}>{children}</span>;
}

// ── Status Dot ─────────────────────────────────────────

interface StatusDotProps {
    status: 'active' | 'idle' | 'error' | 'offline';
}

export function StatusDot({ status }: StatusDotProps) {
    return <span className={`status-dot status-dot--${status}`} />;
}

// ── Empty State ────────────────────────────────────────

interface EmptyStateProps {
    icon?: string;
    title: string;
    description?: string;
    action?: ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
    return (
        <div className="empty-state">
            {icon && <div className="empty-state__icon">{icon}</div>}
            <h3 className="empty-state__title">{title}</h3>
            {description && <p className="empty-state__description">{description}</p>}
            {action && <div style={{ marginTop: 'var(--space-4)' }}>{action}</div>}
        </div>
    );
}

// ── Tabs ───────────────────────────────────────────────

interface TabItem {
    key: string;
    label: string;
    icon?: ReactNode;
}

interface TabsProps {
    items: TabItem[];
    activeKey: string;
    onChange: (key: string) => void;
}

export function Tabs({ items, activeKey, onChange }: TabsProps) {
    return (
        <div className="tabs">
            {items.map(item => (
                <button
                    key={item.key}
                    className={`tabs__item ${item.key === activeKey ? 'tabs__item--active' : ''}`}
                    onClick={() => onChange(item.key)}
                >
                    {item.icon && <span style={{ marginRight: '6px' }}>{item.icon}</span>}
                    {item.label}
                </button>
            ))}
        </div>
    );
}

// ── Section Divider ────────────────────────────────────

export function SectionDivider() {
    return <div className="section-divider" />;
}

// ── Form Group ─────────────────────────────────────────

interface FormGroupProps {
    label: string;
    hint?: string;
    error?: string;
    children: ReactNode;
}

export function FormGroup({ label, hint, error, children }: FormGroupProps) {
    return (
        <div className="form-group">
            <label className="form-group__label">{label}</label>
            {children}
            {hint && !error && <span className="form-group__hint">{hint}</span>}
            {error && <span className="form-group__error">{error}</span>}
        </div>
    );
}

// ── Modal ──────────────────────────────────────────────

interface ModalProps {
    open: boolean;
    onClose: () => void;
    title: string;
    children: ReactNode;
    footer?: ReactNode;
    variant?: 'default' | 'wide' | 'narrow';
}

export function Modal({ open, onClose, title, children, footer, variant = 'default' }: ModalProps) {
    if (!open) return null;

    const contentCls = variant === 'default'
        ? 'modal-content'
        : `modal-content modal-content--${variant}`;

    return (
        <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <div className={contentCls}>
                <div className="modal-header">
                    <h3 className="modal-header__title">{title}</h3>
                    <button className="modal-header__close" onClick={onClose}>✕</button>
                </div>
                {children}
                {footer && <div className="modal-footer">{footer}</div>}
            </div>
        </div>
    );
}

// ── Skeleton Loading ───────────────────────────────────

interface SkeletonProps {
    variant?: 'text' | 'title' | 'avatar';
    width?: string;
    height?: string;
    style?: CSSProperties;
}

export function Skeleton({ variant = 'text', width, height, style }: SkeletonProps) {
    return (
        <div
            className={`skeleton skeleton--${variant}`}
            style={{ width, height, ...style }}
        />
    );
}

// ── Data Table ─────────────────────────────────────────

interface Column<T> {
    key: string;
    title: string;
    render: (item: T) => ReactNode;
    width?: string;
}

interface DataTableProps<T> {
    columns: Column<T>[];
    data: T[];
    rowKey: (item: T) => string;
    onRowClick?: (item: T) => void;
}

export function DataTable<T>({ columns, data, rowKey, onRowClick }: DataTableProps<T>) {
    return (
        <table className="data-table">
            <thead>
                <tr>
                    {columns.map(col => (
                        <th key={col.key} style={{ width: col.width }}>{col.title}</th>
                    ))}
                </tr>
            </thead>
            <tbody>
                {data.map(item => (
                    <tr
                        key={rowKey(item)}
                        onClick={() => onRowClick?.(item)}
                        style={{ cursor: onRowClick ? 'pointer' : undefined }}
                    >
                        {columns.map(col => (
                            <td key={col.key}>{col.render(item)}</td>
                        ))}
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

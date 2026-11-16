/* The bell in the header — the only always-visible sign that something
 * happened while a user was not looking at a project page. ROADMAP.md names
 * the absence of this as the platform's most keenly felt gap: without it, an
 * owner learns of a pending contribution only by visiting the project page,
 * and a contributor learns of a decision the same way.
 *
 * An inline SVG rather than an icon font or emoji, matching styles.css's rule
 * of loading no third-party asset.
 */

import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { notifications as notificationsApi, type NotificationOut } from "../lib/api";

const POLL_MS = 45_000;

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M18 16v-5a6 6 0 1 0-12 0v5l-1.6 2.4A1 1 0 0 0 5.2 20h13.6a1 1 0 0 0 .8-1.6L18 16Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M9.5 21a2.5 2.5 0 0 0 5 0" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export default function NotificationBell() {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<NotificationOut[] | null>(null);
  const [loading, setLoading] = useState(false);
  const boxRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const { count: n } = await notificationsApi.unreadCount();
        if (!cancelled) setCount(n);
      } catch {
        // A missed poll is not worth surfacing — the next one will catch up.
      }
    }
    void poll();
    const id = window.setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    function onClickOutside(event: MouseEvent) {
      if (boxRef.current && !boxRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, [open]);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      try {
        setItems(await notificationsApi.list({ limit: 10 }));
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
  }

  async function markAllRead() {
    await notificationsApi.markAllRead();
    setCount(0);
    setItems((prev) => prev?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null);
  }

  async function openNotification(notification: NotificationOut) {
    if (!notification.read_at) {
      setCount((n) => Math.max(0, n - 1));
      setItems(
        (prev) =>
          prev?.map((n) =>
            n.id === notification.id ? { ...n, read_at: new Date().toISOString() } : n,
          ) ?? null,
      );
      try {
        await notificationsApi.markRead(notification.id);
      } catch {
        // Read state is a convenience, not a source of truth worth blocking on.
      }
    }
    setOpen(false);
    if (notification.project_slug) navigate(`/projects/${notification.project_slug}`);
  }

  return (
    <div className="notification-bell" ref={boxRef}>
      <button
        type="button"
        className="ghost icon-button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={toggle}
      >
        <BellIcon />
        {count > 0 && (
          <span className="notification-count" aria-label={`${count} unread notifications`}>
            {count > 9 ? "9+" : count}
          </span>
        )}
        <span className="visually-hidden">Notifications</span>
      </button>

      {open && (
        <div className="notification-dropdown">
          <div className="notification-dropdown-head">
            <strong>Notifications</strong>
            {count > 0 && (
              <button type="button" className="ghost tiny-button" onClick={markAllRead}>
                Mark all as read
              </button>
            )}
          </div>

          {loading && <p className="muted small">Loading…</p>}
          {!loading && items?.length === 0 && (
            <p className="muted small">No notifications yet.</p>
          )}
          {!loading && items && items.length > 0 && (
            <ul className="notification-list">
              {items.map((notification) => (
                <li key={notification.id}>
                  <button
                    type="button"
                    className={`notification-item${notification.read_at ? "" : " unread"}`}
                    onClick={() => openNotification(notification)}
                  >
                    <span className="notification-title">{notification.title}</span>
                    {notification.body && (
                      <span className="notification-body">{notification.body}</span>
                    )}
                    <span className="notification-time">
                      {new Date(notification.created_at).toLocaleString()}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <Link className="notification-see-all" to="/notifications" onClick={() => setOpen(false)}>
            See all
          </Link>
        </div>
      )}
    </div>
  );
}

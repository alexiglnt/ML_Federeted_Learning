import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { notifications as notificationsApi, type NotificationOut } from "../lib/api";

export default function Notifications() {
  const [items, setItems] = useState<NotificationOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    notificationsApi
      .list({ limit: 100 })
      .then(setItems)
      .catch((caught) =>
        setError(caught instanceof Error ? caught.message : "Could not load notifications."),
      );
  }, []);

  async function markAllRead() {
    await notificationsApi.markAllRead();
    setItems(
      (prev) => prev?.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })) ?? null,
    );
  }

  async function openNotification(notification: NotificationOut) {
    if (!notification.read_at) {
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
    if (notification.project_slug) navigate(`/projects/${notification.project_slug}`);
  }

  const unreadCount = items?.filter((n) => !n.read_at).length ?? 0;

  return (
    <section className="narrow">
      <div className="page-head">
        <h1>Notifications</h1>
        {unreadCount > 0 && (
          <button type="button" className="ghost" onClick={markAllRead}>
            Mark all as read
          </button>
        )}
      </div>

      {error && <p className="muted">{error}</p>}
      {!error && !items && <p className="muted">Loading…</p>}
      {!error && items?.length === 0 && <p className="muted">No notifications yet.</p>}

      {items && items.length > 0 && (
        <ul className="notification-page-list">
          {items.map((notification) => (
            <li key={notification.id}>
              <button
                type="button"
                className={`notification-item${notification.read_at ? "" : " unread"}`}
                onClick={() => openNotification(notification)}
              >
                <span className="notification-title">{notification.title}</span>
                {notification.body && <span className="notification-body">{notification.body}</span>}
                <span className="notification-time">
                  {new Date(notification.created_at).toLocaleString()}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

"""Popularity ranking for collected deals.

Blends original-post reach (views, votes) with on-site engagement
(bookmarks, comments, reactions) over a recent window.
"""
from __future__ import annotations

WEIGHTS = {
    "orig_views": 1,
    "orig_votes": 3,
    "bookmarks": 12,
    "site_comments": 8,
    "reactions": 5,
    "orig_comments": 2,
}
# Cap raw reach so one viral community post can't bury a deal that has
# strong on-site engagement but modest views.
VIEWS_CAP = 2000
VOTES_CAP = 400


async def rank_deals(conn, *, days: int = 7, limit: int = 50) -> list[dict]:
    cur = await conn.execute(
        f"""
        SELECT d.*,
               COALESCE(pa.views, 0)  AS orig_views,
               COALESCE(pa.votes, 0)  AS orig_votes,
               COALESCE(pa.comments, 0) AS orig_comment_count,
               COALESCE(bm.n, 0)      AS bookmark_count,
               COALESCE(rc.n, 0)      AS reaction_count,
               COALESCE(cc.n, 0)      AS site_comment_count,
               (MIN(COALESCE(pa.views, 0), {VIEWS_CAP}) * {WEIGHTS["orig_views"]}
                + MIN(COALESCE(pa.votes, 0), {VOTES_CAP}) * {WEIGHTS["orig_votes"]}
                + COALESCE(bm.n, 0) * {WEIGHTS["bookmarks"]}
                + COALESCE(cc.n, 0) * {WEIGHTS["site_comments"]}
                + COALESCE(rc.n, 0) * {WEIGHTS["reactions"]}
                + COALESCE(pa.comments, 0) * {WEIGHTS["orig_comments"]}) AS popularity
        FROM deals d
        LEFT JOIN (
            SELECT dp.deal_id,
                   SUM(p.views) AS views, SUM(p.votes) AS votes, SUM(p.comments) AS comments
            FROM deal_posts dp JOIN posts p ON p.id = dp.post_id
            GROUP BY dp.deal_id
        ) pa ON pa.deal_id = d.id
        LEFT JOIN (SELECT deal_id, COUNT(*) AS n FROM user_bookmarks GROUP BY deal_id) bm ON bm.deal_id = d.id
        LEFT JOIN (SELECT deal_id, COUNT(*) AS n FROM deal_reactions GROUP BY deal_id) rc ON rc.deal_id = d.id
        LEFT JOIN (
            SELECT deal_id, COUNT(*) AS n FROM deal_comments
            WHERE deleted_at IS NULL GROUP BY deal_id
        ) cc ON cc.deal_id = d.id
        WHERE d.last_seen_at >= datetime('now', ?)
        ORDER BY popularity DESC, d.last_seen_at DESC, d.id DESC
        LIMIT ?
        """,
        (f"-{int(days)} days", int(limit)),
    )
    return [dict(r) for r in await cur.fetchall()]

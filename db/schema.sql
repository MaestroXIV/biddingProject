-- BoardBase schema (SPEC 5). One SQLite file: data/boardbase.db.
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS site (
    id INTEGER PRIMARY KEY, code TEXT UNIQUE, note TEXT);        -- 'EBL' | 'WBF'

CREATE TABLE IF NOT EXISTS tournament (
    id INTEGER PRIMARY KEY, site_id INT REFERENCES site,
    slug TEXT, tourn_code INT, name TEXT, series TEXT,
    year INT, venue TEXT, asp_base_url TEXT,
    ingested_at TEXT, UNIQUE(site_id, tourn_code));

CREATE TABLE IF NOT EXISTS team (
    id INTEGER PRIMARY KEY, tournament_id INT, ext_id INT,
    name TEXT, UNIQUE(tournament_id, ext_id));

CREATE TABLE IF NOT EXISTS player (
    id INTEGER PRIMARY KEY, canonical_name TEXT, country TEXT);

CREATE TABLE IF NOT EXISTS player_alias (
    alias TEXT, player_id INT REFERENCES player,
    PRIMARY KEY(alias, player_id));

CREATE TABLE IF NOT EXISTS round (
    id INTEGER PRIMARY KEY, tournament_id INT, number INT,
    label TEXT, UNIQUE(tournament_id, number));

CREATE TABLE IF NOT EXISTS match (
    id INTEGER PRIMARY KEY, round_id INT, ext_match_id INT,
    home_team_id INT, visiting_team_id INT,
    UNIQUE(round_id, ext_match_id));

CREATE TABLE IF NOT EXISTS seating (
    match_id INT, room TEXT CHECK(room IN ('Open','Closed')),
    seat TEXT CHECK(seat IN ('N','E','S','W')),
    player_id INT, PRIMARY KEY(match_id, room, seat));

CREATE TABLE IF NOT EXISTS deal (
    id INTEGER PRIMARY KEY, round_id INT, board_no INT,
    dealer TEXT, vul TEXT CHECK(vul IN ('NONE','NS','EW','ALL')),
    hand_n TEXT, hand_e TEXT, hand_s TEXT, hand_w TEXT,
    source_url TEXT, UNIQUE(round_id, board_no));

CREATE TABLE IF NOT EXISTS board_instance (
    id INTEGER PRIMARY KEY, deal_id INT, match_id INT,
    room TEXT, contract TEXT, declarer TEXT, lead TEXT,
    tricks INT, score_ns INT, score_ew INT,
    UNIQUE(deal_id, match_id, room));

CREATE TABLE IF NOT EXISTS auction (
    board_instance_id INT PRIMARY KEY REFERENCES board_instance,
    calls TEXT, complete INT,
    opener_seat TEXT, opener_rel_pos INT,
    opening_call TEXT, opener_player_id INT,
    opening_side TEXT CHECK(opening_side IN ('NS','EW')),
    competitive INT,
    vul_rel TEXT CHECK(vul_rel IN ('none','both','fav','unfav')),
    from_opener TEXT,
    uncontested_key TEXT);
CREATE INDEX IF NOT EXISTS ix_auction_open ON auction(opening_call, opener_player_id);
CREATE INDEX IF NOT EXISTS ix_auction_seq  ON auction(from_opener);
CREATE INDEX IF NOT EXISTS ix_auction_unc  ON auction(uncontested_key);

CREATE TABLE IF NOT EXISTS instance_side (
    board_instance_id INT, side TEXT CHECK(side IN ('NS','EW')),
    player_lo INT, player_hi INT, pair_key TEXT,
    PRIMARY KEY(board_instance_id, side));
CREATE INDEX IF NOT EXISTS ix_side_pair ON instance_side(pair_key);

CREATE TABLE IF NOT EXISTS hand_feature (
    deal_id INT, seat TEXT, hcp INT, shape TEXT,
    pattern TEXT, balanced INT, longest_suit TEXT,
    PRIMARY KEY(deal_id, seat));

CREATE TABLE IF NOT EXISTS decision (
    id INTEGER PRIMARY KEY, deal_id INT, seat TEXT,
    kind TEXT CHECK(kind IN ('open','overcall')),
    context_opening TEXT, n INT, dist TEXT,
    top_call TEXT, alt_share REAL);

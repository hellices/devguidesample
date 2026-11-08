-- Lab catalog so movie pages work without TMDB_API_KEY. Re-running is a no-op.
INSERT INTO movies (tmdb_id, title, original_title, release_date, genres, synced_at, created_at) VALUES
  (27205, '인셉션', 'Inception', DATE '2010-07-15', 'SF, 액션', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (157336, '인터스텔라', 'Interstellar', DATE '2014-11-05', 'SF, 드라마', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (155, '다크 나이트', 'The Dark Knight', DATE '2008-07-16', '액션, 범죄', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (496243, '기생충', 'Parasite', DATE '2019-05-30', '코미디, 드라마', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (603, '매트릭스', 'The Matrix', DATE '1999-03-31', 'SF, 액션', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (129, '센과 치히로의 행방불명', '千と千尋の神隠し', DATE '2001-07-20', '애니메이션, 판타지', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (238, '대부', 'The Godfather', DATE '1972-03-14', '드라마, 범죄', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (680, '펄프 픽션', 'Pulp Fiction', DATE '1994-09-10', '범죄, 스릴러', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (13, '포레스트 검프', 'Forrest Gump', DATE '1994-06-23', '드라마, 로맨스', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (550, '파이트 클럽', 'Fight Club', DATE '1999-10-15', '드라마', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (872585, '오펜하이머', 'Oppenheimer', DATE '2023-07-19', '드라마, 역사', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
  (438631, '듄', 'Dune', DATE '2021-09-15', 'SF, 모험', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (tmdb_id) DO NOTHING;

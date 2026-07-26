UPDATE hefei_roads r
SET source = v.id
FROM hefei_roads_vertices_pgr v
WHERE v.osm_id = r.u;

UPDATE hefei_roads r
SET target = v.id
FROM hefei_roads_vertices_pgr v
WHERE v.osm_id = r.v;

const server = require('express')();
const { Client } = require('pg');
const path = require('path');

const client = new Client({
  user: 'postgres',
  host: 'postgres',
  database: 'postgres',
  password: 'postgres',
  port: 5432
});

client.connect();

server.get('/', (req, res) => {
  // serve html page
  res.sendFile(path.join(__dirname, '/index.html'));
});

server.get('/tiles/:zoom/:x/:y', (req, res) => {
  const z = parseInt(req.params.zoom);
  const x = parseInt(req.params.x);
  const y = parseInt(req.params.y);
  console.log(z, x, y);
  const swLong = tile2long(x, z);
  const swLat = tile2lat(y + 1, z);
  const neLong = tile2long(x + 1, z);
  const neLat = tile2lat(y, z);
  const boundingBox = {};
  boundingBox.xmin = swLong;
  boundingBox.ymin = swLat;
  boundingBox.xmax = neLong;
  boundingBox.ymax = neLat;
  const DENSIFY_FACTOR = 4;
  const segSize = (boundingBox.xmax - boundingBox.xmin) / DENSIFY_FACTOR;
  const bounds = `ST_Segmentize(ST_MakeEnvelope(${boundingBox.xmin}, ${boundingBox.ymin}, ${boundingBox.xmax}, ${boundingBox.ymax}, 4326),${segSize})`;
  const sqlTemplate = `WITH mvtgeom as (SELECT ST_AsMVTGeom(ST_GeomFromEWKB(geom.wkb_geometry),
  ${bounds}::box2d) AS geom, *
  FROM countries as geom
  where ST_Intersects(${bounds}, ST_SetSRID(ST_GeomFromEWKB(geom.wkb_geometry), 4326))) SELECT ST_AsMVT(mvtgeom.*) FROM mvtgeom`;

  client.query(sqlTemplate, (err, response) => {
    console.log(err, response);
    res.set({
      'Access-Control-Allow-Origin': '*',
      'Content-type': 'application/vnd.mapbox-vector-tile'
    });
    if (response && response.rows.length > 0) {
      res.status(200).write(response.rows[0].st_asmvt);
    } else {
      res.status(404).send('Not found');
    }
    res.end();
  });
});

/**
 * Helper function to convert tile to longitude
 *
 * @param {number} x X-coordinate of the tile
 * @param {number} z Z-coordinate of the tile
 * @returns {number} x/y/z to longitude
 */
function tile2long (x, z) {
  return x / Math.pow(2, z) * 360 - 180;
}

/**
 * Helper function to convert tile to latitude
 *
 * @param {number} y Y-coordinate of the tile
 * @param {number} z Z-coordinate of the tile
 * @returns {number} x/y/z to latitude
 */
function tile2lat (y, z) {
  const n = Math.PI - 2 * Math.PI * y / Math.pow(2, z);
  return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
}

server.listen(8080, () => console.log(`listening on ${8080}`));

const server = require('express')();

server.get('/', (req, res) => {
  res.json({ message: 'Hello World!' });
})

server.listen(8080, () => console.log(`listening on ${8080}`));
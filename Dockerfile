FROM node:17
WORKDIR /src
COPY package* .
RUN npm install
COPY src/* .
CMD ["node", "index.js"]
FROM node:17
WORKDIR /src
COPY package* .
RUN npm install
COPY index.js .
CMD ["node", "index.js"]
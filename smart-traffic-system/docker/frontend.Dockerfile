FROM node:20-alpine

WORKDIR /app
COPY frontend/package.json ./package.json
COPY frontend/vite.config.js ./vite.config.js
COPY frontend/index.html ./index.html
COPY frontend/src ./src
COPY frontend/components ./components
RUN npm install

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

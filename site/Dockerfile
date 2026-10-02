FROM node:22-alpine AS build
WORKDIR /src
RUN apk add --no-cache libc6-compat
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ENV NODE_OPTIONS=--max-old-space-size=1536
RUN npm run build

FROM python:3.12-slim
WORKDIR /site
RUN pip install --no-cache-dir psycopg2-binary==2.9.10
COPY --from=build /src/dist ./dist
COPY server.py dbmap.py ./
EXPOSE 80
CMD ["python", "server.py"]

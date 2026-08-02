FROM node:20-slim

RUN apt-get update && apt-get install -y \
    ffmpeg \
    fontconfig \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY package*.json ./
RUN npm install --production
COPY . .

# Install the real Inter fonts system-wide so libass (used by the ASS
# caption/template rendering) can find them via fontconfig.
RUN mkdir -p /usr/share/fonts/truetype/custom && \
    cp motion-assets/fonts/*.ttf /usr/share/fonts/truetype/custom/ && \
    fc-cache -f

EXPOSE 4000
CMD ["node", "compose.js"]

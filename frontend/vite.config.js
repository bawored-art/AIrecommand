import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

// GitHub Pages 프로젝트 사이트(https://<user>.github.io/<repo>/)에 배포되므로
// 상대 경로 base를 써서 어떤 서브 경로에 배포되어도 자산 경로가 깨지지 않게 한다.
export default defineConfig({
  base: "./",
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/icon-192.png", "icons/icon-512.png"],
      manifest: {
        name: "AI 알트코인 리서치 에이전트",
        short_name: "알트코인 리서치",
        description: "펀더멘털은 오르는데 가격은 아직 반영하지 않은 코인을 찾는 리서치 대시보드",
        theme_color: "#0f172a",
        background_color: "#0f172a",
        display: "standalone",
        start_url: "./",
        scope: "./",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // data/*.json은 배포 때마다 최신 데이터로 바뀌므로 network-first로 캐시해
        // 온라인일 때는 항상 최신을, 오프라인일 때만 마지막 캐시를 보여준다.
        runtimeCaching: [
          {
            urlPattern: /\/data\/.*\.json$/,
            handler: "NetworkFirst",
            options: { cacheName: "data-cache", networkTimeoutSeconds: 5 },
          },
        ],
      },
    }),
  ],
});

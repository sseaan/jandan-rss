// 让阅读器可以继续用 /feed.xml 订阅，实际交给 /feed 这个云函数。
export const config = {
  matcher: ["/feed.xml"],
};

export function middleware(context) {
  return context.rewrite("/feed");
}

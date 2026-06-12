interface Env {
  GITHUB_TOKEN: string;
  GITHUB_OWNER: string;
  GITHUB_REPO: string;
  GITHUB_WORKFLOW_ID: string;
  GITHUB_REF: string;
  SERVICE_LABEL: string;
  TARGET_TIMEZONE: string;
  TARGET_HOUR: string;
  TARGET_MINUTE: string;
}

type BerlinSlot = {
  hour: string;
  minute: string;
  isoDate: string;
};

function getTargetSlot(scheduledTime: number, timeZone: string): BerlinSlot {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(scheduledTime));

  const value = (type: Intl.DateTimeFormatPartTypes): string => {
    const part = parts.find((item) => item.type === type);
    if (!part) {
      throw new Error(`Missing ${type} in formatted scheduled time`);
    }
    return part.value;
  };

  return {
    hour: value("hour"),
    minute: value("minute"),
    isoDate: `${value("year")}-${value("month")}-${value("day")}`,
  };
}

function shouldDispatch(controller: ScheduledController, env: Env): boolean {
  const slot = getTargetSlot(controller.scheduledTime, env.TARGET_TIMEZONE);
  return slot.hour === env.TARGET_HOUR && slot.minute === env.TARGET_MINUTE;
}

async function dispatchGitHubWorkflow(env: Env): Promise<void> {
  const url = new URL(
    `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/${env.GITHUB_WORKFLOW_ID}/dispatches`,
  );

  const response = await fetch(url, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      "Content-Type": "application/json",
      "User-Agent": "adanos-retail-stock-signals-scheduler",
      "X-GitHub-Api-Version": "2026-03-10",
    },
    body: JSON.stringify({
      ref: env.GITHUB_REF,
      inputs: {
        scheduler: "cloudflare-cron",
      },
    }),
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub workflow dispatch failed: ${response.status} ${body}`);
  }
}

export default {
  async scheduled(controller: ScheduledController, env: Env): Promise<void> {
    const slot = getTargetSlot(controller.scheduledTime, env.TARGET_TIMEZONE);

    if (!shouldDispatch(controller, env)) {
      console.log(
        `${env.SERVICE_LABEL}: skipping duplicate DST slot for ${slot.isoDate} ${slot.hour}:${slot.minute} ${env.TARGET_TIMEZONE}`,
      );
      return;
    }

    console.log(
      `${env.SERVICE_LABEL}: dispatching ${env.GITHUB_OWNER}/${env.GITHUB_REPO}/${env.GITHUB_WORKFLOW_ID} for ${slot.isoDate}`,
    );
    await dispatchGitHubWorkflow(env);
  },

  async fetch(): Promise<Response> {
    return new Response("Adanos Retail Stock Signals Scheduler\n", {
      headers: {
        "content-type": "text/plain; charset=utf-8",
      },
    });
  },
};

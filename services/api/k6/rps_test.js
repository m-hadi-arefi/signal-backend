import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  scenarios: {
    stress: {
      executor: 'ramping-arrival-rate',
      startRate: 50,
      timeUnit: '1s',
      preAllocatedVUs: 200,
      maxVUs: 2000,
      stages: [
        { target: 100, duration: '30s' },
        { target: 500, duration: '1m' },
        { target: 1000, duration: '1m' },
        { target: 2000, duration: '1m' },
        { target: 3000, duration: '1m' },
        { target: 0, duration: '30s' },
      ],
    },
  },

  thresholds: {
    http_req_failed: ['rate<0.01'],      // <1% error
    http_req_duration: ['p(95)<500'],    // p95 زیر 500ms
  },
};

export default function () {
  const res = http.get('http://api:8080/v1/events');

  check(res, {
    'status is 200': (r) => r.status === 200,
  });

  sleep(0.01);
}
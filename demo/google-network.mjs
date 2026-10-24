import { lookup as systemLookup } from "node:dns";
import { Resolver } from "node:dns/promises";
import { Agent, fetch as undiciFetch } from "undici";

const googleApiHost = "generativelanguage.googleapis.com";
const publicResolver = new Resolver();
publicResolver.setServers(["8.8.8.8"]);

export function createGoogleLookup(
  lookup = systemLookup,
  resolve4 = (hostname) => publicResolver.resolve4(hostname)
) {
  return (hostname, options, callback) => {
    lookup(hostname, options, (error, address, family) => {
      if (!error || hostname !== googleApiHost || !["ENOTFOUND", "EAI_AGAIN"].includes(error.code)) {
        callback(error, address, family);
        return;
      }
      resolve4(hostname).then(
        (addresses) => {
          if (!addresses.length) {
            callback(error);
          } else if (options?.all) {
            callback(null, addresses.map((resolved) => ({ address: resolved, family: 4 })));
          } else {
            callback(null, addresses[0], 4);
          }
        },
        () => callback(error)
      );
    });
  };
}

const googleDispatcher = new Agent({ connect: { lookup: createGoogleLookup() } });

export function googleApiFetch(input, init) {
  return undiciFetch(input, { ...init, dispatcher: googleDispatcher });
}

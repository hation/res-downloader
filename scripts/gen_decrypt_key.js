// 生成微信视频解密密钥（ISAAC64）
// 用法: node gen_decrypt_key.js <decodeKey>
// 输出: base64编码的密钥

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const decodeKey = process.argv[2];
if (!decodeKey) {
  console.error('用法: node gen_decrypt_key.js <decodeKey>');
  process.exit(1);
}

// 加载decrypt.js
const decryptPath = path.join(__dirname, '..', 'frontend', 'src', 'assets', 'js', 'decrypt.js');
let code = fs.readFileSync(decryptPath, 'utf8');
code = code.replace(/export \{getDecryptionArray\}/, 'global.__getDecryptionArray = getDecryptionArray');

const context = {
  console: console,
  require: require,
  module: { exports: {} },
  __dirname: path.dirname(decryptPath),
  __filename: decryptPath,
  process: process,
  Buffer: Buffer,
  TextEncoder: TextEncoder,
  TextDecoder: TextDecoder,
  URL: URL,
};
context.global = context;
context.self = context;
context.window = context;

vm.createContext(context);
vm.runInContext(code, context, { filename: decryptPath });

// 等待WASM初始化
const waitForModule = () => {
  return new Promise((resolve, reject) => {
    const check = () => {
      if (context.__getDecryptionArray) {
        try {
          const key = context.__getDecryptionArray(decodeKey);
          resolve(Buffer.from(key).toString('base64'));
        } catch (e) {
          reject(e);
        }
      } else {
        setTimeout(check, 50);
      }
    };
    setTimeout(check, 100);
    setTimeout(() => reject(new Error('WASM初始化超时')), 10000);
  });
};

waitForModule()
  .then(b64 => {
    process.stdout.write(b64);
    process.exit(0);
  })
  .catch(err => {
    console.error('生成密钥失败:', err.message);
    process.exit(1);
  });

import apt, apt.debfile
import pathlib, stat, shutil, urllib.request, subprocess, getpass, time, tempfile
import secrets, json, re
import IPython.utils.io

def _installPkg(cache, name):
  pkg = cache[name]
  if pkg.is_installed:
    print(f"{name} is already installed")
  else:
    print(f"Install {name}")
    pkg.mark_install()

def _installPkgs(cache, *args):
  for i in args:
    _installPkg(cache, i)

def _download(url, path):
  try:
    with urllib.request.urlopen(url) as response:
      with open(path, 'wb') as outfile:
        shutil.copyfileobj(response, outfile)
  except:
    print("Failed to download ", url)
    raise

def _setupSSHDImpl(ngrok_token, ngrok_region, custom_ngrok_server):
  #apt-get update
  #apt-get upgrade
  cache = apt.Cache()
  cache.update()
  cache.open(None)
  cache.upgrade()
  cache.commit()

  subprocess.run(["unminimize"], input = "y\n", check = True, universal_newlines = True)

  _installPkg(cache, "openssh-server")
  cache.commit()

  #Reset host keys
  for i in pathlib.Path("/etc/ssh").glob("ssh_host_*_key"):
    i.unlink()
  subprocess.run(
                  ["ssh-keygen", "-A"],
                  check = True)

  #Prevent ssh session disconnection.
  with open("/etc/ssh/sshd_config", "a") as f:
    f.write("\n\nClientAliveInterval 120\n")

  print("ECDSA key fingerprint of host:")
  ret = subprocess.run(
                ["ssh-keygen", "-lvf", "/etc/ssh/ssh_host_ecdsa_key.pub"],
                stdout = subprocess.PIPE,
                check = True,
                universal_newlines = True)
  print(ret.stdout)

  _download("https://bin.equinox.io/c/4VmDzA7iaHb/ngrok-stable-linux-amd64.zip", "ngrok.zip")
  shutil.unpack_archive("ngrok.zip")
  pathlib.Path("ngrok").chmod(stat.S_IXUSR)

  root_password = secrets.token_urlsafe()
  user_password = secrets.token_urlsafe()
  user_name = "colab"
  print("✂️"*24)
  print(f"root password: {root_password}")
  print(f"{user_name} password: {user_password}")
  print("✂️"*24)
  subprocess.run(["useradd", "-s", "/bin/bash", "-m", user_name])
  subprocess.run(["adduser", user_name, "sudo"], check = True)
  subprocess.run(["chpasswd"], input = f"root:{root_password}", universal_newlines = True)
  subprocess.run(["chpasswd"], input = f"{user_name}:{user_password}", universal_newlines = True)
  subprocess.run(["service", "ssh", "restart"])

  if not pathlib.Path('/root/.ngrok2/ngrok.yml').exists():
    subprocess.run(["./ngrok", "authtoken", ngrok_token])

  #https://github.com/inconshreveable/ngrok/blob/master/docs/SELFHOSTING.md#5-configure-the-client
  if custom_ngrok_server != None:
    with open('/root/.ngrok2/ngrok.yml', 'a') as f:
      f.write(f"\n\nserver_addr: {custom_ngrok_server}\n")
      f.write("trust_host_root_certs: true\n")

  ngrok_args = ["./ngrok", "tcp"]
  if ngrok_region != None:
    ngrok_args += ["-region", ngrok_region]
  ngrok_args.append("22")
  ngrok_proc = subprocess.Popen(ngrok_args)
  time.sleep(2)
  if ngrok_proc.poll() != None:
    raise RuntimeError("Failed to run ngrok. Return code:" + str(ngrok_proc.returncode) + "\nSee runtime log for more info.")

  with urllib.request.urlopen("http://localhost:4040/api/tunnels") as response:
    url = json.load(response)['tunnels'][0]['public_url']
    m = re.match("tcp://(.+):(\d+)", url)

  hostname = m.group(1)
  port = m.group(2)

  ssh_common_options =  "-o UserKnownHostsFile=/dev/null -o VisualHostKey=yes"
  print("---")
  print("Command to connect to the ssh server:")
  print("✂️"*24)
  print(f"ssh {ssh_common_options} -p {port} {user_name}@{hostname}")
  print("✂️"*24)
  print("---")
  print("If you use VNC:")
  print("✂️"*24)
  print(f"ssh {ssh_common_options} -L 5901:localhost:5901 -p {port} {user_name}@{hostname}")
  print("✂️"*24)

def setupSSHD(ngrok_region = None, check_gpu_available = False, custom_ngrok_server = None):
  if check_gpu_available and not _check_gpu_available():
    return False

  print("---")
  print("Copy&paste your tunnel authtoken from https://dashboard.ngrok.com/auth")
  print("(You need to sign up for ngrok and login,)")
  #Set your ngrok Authtoken.
  ngrok_token = getpass.getpass()

  if not ngrok_region and custom_ngrok_server == None:
    print("Select your ngrok region:")
    print("us - United States (Ohio)")
    print("eu - Europe (Frankfurt)")
    print("ap - Asia/Pacific (Singapore)")
    print("au - Australia (Sydney)")
    print("sa - South America (Sao Paulo)")
    print("jp - Japan (Tokyo)")
    print("in - India (Mumbai)")
    ngrok_region = region = input()

  _setupSSHDImpl(ngrok_token, ngrok_region, custom_ngrok_server)
  return True

def _setupVNC():
  libjpeg_ver = "2.0.3"
  turboVNC_ver = "2.2.3"

  libjpeg_url = "https://svwh.dl.sourceforge.net/project/libjpeg-turbo/{0}/libjpeg-turbo-official_{0}_amd64.deb".format(libjpeg_ver)
  turboVNC_url = "https://svwh.dl.sourceforge.net/project/turbovnc/{0}/turbovnc_{0}_amd64.deb".format(turboVNC_ver)

  _download(libjpeg_url, "libjpeg-turbo.deb")
  _download(turboVNC_url, "turbovnc.deb")
  cache = apt.Cache()
  apt.debfile.DebPackage("libjpeg-turbo.deb", cache).install()
  apt.debfile.DebPackage("turbovnc.deb", cache).install()

  _installPkgs(cache, "lxde", "firefox")
  cache.commit()

  vnc_sec_conf_p = pathlib.Path("/etc/turbovncserver-security.conf")
  vnc_sec_conf_p.write_text("""\
no-remote-connections
no-httpd
no-x11-tcp-connections
""")

  vncrun_py = tempfile.gettempdir() / pathlib.Path("vncrun.py")
  vncrun_py.write_text("""\
import subprocess, secrets, pathlib

vnc_passwd = secrets.token_urlsafe()[:8]
vnc_viewonly_passwd = secrets.token_urlsafe()[:8]
print("✂️"*24)
print("VNC password: {}".format(vnc_passwd))
print("VNC view only password: {}".format(vnc_viewonly_passwd))
print("✂️"*24)
vncpasswd_input = "{0}\\n{1}".format(vnc_passwd, vnc_viewonly_passwd)
vnc_user_dir = pathlib.Path.home().joinpath(".vnc")
vnc_user_dir.mkdir(exist_ok=True)
vnc_user_passwd = vnc_user_dir.joinpath("passwd")
with vnc_user_passwd.open('wb') as f:
  subprocess.run(
    ["/opt/TurboVNC/bin/vncpasswd", "-f"],
    stdout=f,
    input=vncpasswd_input,
    universal_newlines=True)
vnc_user_passwd.chmod(0o600)
subprocess.run(
  ["/opt/TurboVNC/bin/vncserver"]
)

#Disable screensaver because no one would want it.
(pathlib.Path.home() / ".xscreensaver").write_text("mode: off\\n")
""")
  r = subprocess.run(
                    ["su", "-c", "python3 " + str(vncrun_py), "colab"],
                    check = True,
                    stdout = subprocess.PIPE,
                    universal_newlines = True)
  print(r.stdout)

def setupVNC(ngrok_region = None, custom_ngrok_server = None):
  if setupSSHD(ngrok_region, True, custom_ngrok_server):
    _setupVNC()

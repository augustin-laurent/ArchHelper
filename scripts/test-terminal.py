import argparse,codecs,fcntl,html,json,os,pathlib,pty,select,signal,struct,sys,termios,time
import pyte

# Linux console uses ECMA-48 HPA (CSI `); pyte 0.8.2 only aliases CHA.
pyte.Stream.csi["`"] = "cursor_to_column"

parser=argparse.ArgumentParser(description="Exercise the demo in a real pseudo-terminal. No backend or disk access.")
parser.add_argument('--binary',type=pathlib.Path,required=True)
parser.add_argument('--output',type=pathlib.Path,required=True)
parser.add_argument('--lang',choices=('fr','en'),default='fr')
parser.add_argument('--width',type=int,default=120)
parser.add_argument('--height',type=int,default=32)
parser.add_argument('--luks',action='store_true')
parser.add_argument('--console',action='store_true')
parser.add_argument('--select-package',action='store_true')
parser.add_argument('--search-timezone',action='store_true')
parser.add_argument('--short-password',action='store_true')
args=parser.parse_args()
output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
def tr(fr,en):return en if args.lang=='en' else fr
screen=pyte.Screen(args.width,args.height);stream=pyte.Stream(screen);decoder=codecs.getincrementaldecoder('utf-8')('replace')
pid,fd=pty.fork()
if pid==0:
 os.environ.pop('NO_COLOR',None)
 os.environ.update(TERM='linux' if args.console else 'xterm-256color',COLORTERM='' if args.console else 'truecolor')
 os.execv(str(args.binary.resolve()),['archhelper-install','--demo','--lang',args.lang])
fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',args.height,args.width,0,0))

def pump(seconds=.15):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  if select.select([fd],[],[],max(0,end-time.monotonic()))[0]:
   try:data=os.read(fd,65536)
   except OSError:return
   text=decoder.decode(data);stream.feed(text)
   if '\x1b[6n' in text:os.write(fd,b'\x1b[1;1R')
def wait(text):
 end=time.monotonic()+8
 while time.monotonic()<end:
  pump(.1)
  if text in '\n'.join(screen.display):pump(.12);return
 raise RuntimeError('Missing screen '+text+'\n'+'\n'.join(screen.display))
def key(data='\r'):os.write(fd,data.encode());pump(.2)
colors={'default':'#e4e8de','black':'#14201c','red':'#f0aa83','green':'#c9df83','brown':'#e4ad78','blue':'#93a99a','magenta':'#e4ad78','cyan':'#a5c8bb','white':'#e4e8de'}
def color(name,bg=False):
 if name=='default':return '#14201c' if bg else '#e4e8de'
 return colors.get(name,'#'+name if len(name)==6 else '#e4e8de')
def capture(name):
 width,height=screen.columns*10+40,screen.lines*21+60
 pieces=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',f'<rect width="{width}" height="{height}" rx="14" fill="#14201c"/>','<g font-family="DejaVu Sans Mono,monospace" font-size="16">']
 for y in range(screen.lines):
  for x in range(screen.columns):
   c=screen.buffer[y][x];bg=color(c.bg,True)
   if bg!='#14201c':pieces.append(f'<rect x="{x*10+20}" y="{y*21+24}" width="10" height="21" fill="{bg}"/>')
   if c.data.strip():pieces.append(f'<text x="{x*10+20}" y="{y*21+41}" fill="{color(c.fg)}" font-weight="{"bold" if c.bold else "normal"}">{html.escape(c.data)}</text>')
 pieces+=['</g>','</svg>'];(output/(name+'.svg')).write_text(''.join(pieces))
 (output/(name+'.txt')).write_text('\n'.join(screen.display))
try:
 wait(tr('Bienvenue','Welcome'));capture('archhelper-accueil')
 key();wait('[OK]')
 key();wait(tr('Connecté','Online'))
 key();wait(tr("Langue de l'interface",'Interface language'))
 key();wait(tr('Langue du système','System locale'))
 wait('fr_FR.UTF-8');capture('archhelper-langue-systeme')
 key();wait(tr('Clavier de la console','Console keyboard'))
 key();wait(tr('Clavier graphique','Graphical and SDDM keyboard'))
 key();wait(tr('Fuseau horaire','Time zone'))
 if args.search_timezone:
  key('/');key('Etc/GMT+3');wait('Etc/GMT+3')
 key();wait(tr('Disque cible','Target disk'));capture('archhelper-disque')
 key();wait(tr('Partitionnement','Partitioning'))
 key();wait(tr('Utilisateur administrateur','Administrator username'))
 key();wait(tr('Nom de la machine','Hostname'))
 key();wait(tr('Mot de passe','Password'))
 password='1234' if args.short_password else 'demo-pass-123'
 key(password);key();wait(tr('Confirmer le mot de passe','Confirm password'))
 key(password);key();wait(tr('Mot de passe root facultatif','Optional root password'))
 key();wait(tr('Confirmer le mot de passe root','Confirm root password'))
 key();wait(tr('Bureau Wayland','Wayland desktop'))
 key();wait(tr('Activer le dépôt CachyOS','Enable CachyOS repository'))
 key();wait(tr('Noyau','Kernel'))
 key();wait(tr('Pilotes graphiques','Graphics drivers'))
 key();wait('UKI')
 key();wait('Plymouth')
 key();wait(tr('Chiffrer la racine','Encrypt root'))
 if args.luks:key('y')
 else:key()
 wait(tr('Gestion du réseau','Network management'))
 key();wait(tr('Instantanés','Snapshots'))
 key();wait('Bluetooth')
 key();wait('ZRAM')
 key();wait(tr('Swap sur disque','Disk swap'))
 key();wait(tr('Emplacement du swap','Swap location'))
 key()
 if args.luks:
  wait(tr('Phrase secrète LUKS2','LUKS2 passphrase'))
  key('demo-luks-123');key();wait(tr('Confirmer LUKS2','Confirm LUKS2'))
  key('demo-luks-123');key()
 wait(tr('Paquets supplémentaires','Additional packages'))
 if args.select_package:
  key('/');key('firefox');key();key(' ')
 key()
 wait(tr('Récapitulatif','Review'));wait('SIMULATION');capture('archhelper-recapitulatif')
 if args.select_package or args.search_timezone:
  key('\x1b[6~')
  if args.search_timezone:wait('Etc/GMT+3')
  if args.select_package:wait('firefox')
 key();wait(tr('Appliquer les modifications','Apply changes'))
 key('y');wait('Installation');pump(.8);capture('archhelper-installation')
 wait(tr('Arch Linux est installé.','Arch Linux is installed.'));capture('archhelper-termine')
 key();pump(.2)
 print(json.dumps({'terminal':f'{args.width}x{args.height}','language':args.lang,'luks':args.luks,'console':args.console,'demo':'complete','screenshots':5,'backend_started':False}))
finally:
 try:os.kill(pid,signal.SIGKILL)
 except ProcessLookupError:pass
 os.waitpid(pid,0)

